import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'
import { useAIConsentGate } from './useAIConsentGate'

export function QuillSetupWithPostHogAIButton({
    source,
    size,
}: {
    source: CatalogSetupSource
    size?: 'default' | 'sm'
}): JSX.Element {
    const { startSetupWithPostHogAI, rememberSetupIntent, resumeSetupIntent } = useActions(catalogSetupLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const consentGate = useAIConsentGate(() => startSetupWithPostHogAI(source), {
        onBeforeApprove: () => rememberSetupIntent(source),
        pendingRedirectUrl: urls.dataCatalog('metrics'),
    })

    // Finishes a click that an SSO reauthentication interrupted, once consent is in place. While the
    // popover is open, `onApprove` starts setup itself, so resuming then would start it twice.
    useEffect(() => {
        if (dataProcessingAccepted && !consentGate.consentOpen) {
            resumeSetupIntent()
        }
    }, [dataProcessingAccepted, consentGate.consentOpen, resumeSetupIntent])

    return (
        // `ignoreDismissal` keeps the popover reachable after a previous dismissal, so a click without
        // consent always has a way to grant it.
        <AIConsentPopoverWrapper ignoreDismissal {...consentGate.popover}>
            <Button
                variant="primary"
                size={size}
                onClick={consentGate.onClick}
                // pinned: data-attr values feed autocapture dashboards
                data-attr={`data-catalog-setup-with-ai-${source}`}
            >
                <IconSparkles />
                Set up with PostHog AI
            </Button>
        </AIConsentPopoverWrapper>
    )
}

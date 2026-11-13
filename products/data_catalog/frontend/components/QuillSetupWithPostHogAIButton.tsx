import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'

export function QuillSetupWithPostHogAIButton({
    source,
    size,
}: {
    source: CatalogSetupSource
    size?: 'default' | 'sm'
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { startSetupWithPostHogAI } = useActions(catalogSetupLogic)
    const start = (): void => startSetupWithPostHogAI(source)

    return (
        // `ignoreDismissal` keeps the consent popover reachable after a previous dismissal, so an
        // unapproved click always has a way to grant consent rather than doing nothing.
        <AIConsentPopoverWrapper onApprove={start} ignoreDismissal>
            <Button
                variant="primary"
                size={size}
                // The wrapper does not swallow the click. Without this guard an unapproved click would
                // start setup here and again from `onApprove`.
                onClick={() => dataProcessingAccepted && start()}
                // pinned: data-attr values feed autocapture dashboards
                data-attr={`data-catalog-setup-with-ai-${source}`}
            >
                <IconSparkles />
                Set up with PostHog AI
            </Button>
        </AIConsentPopoverWrapper>
    )
}

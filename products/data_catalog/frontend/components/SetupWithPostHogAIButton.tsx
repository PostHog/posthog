import { IconSparkles } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { CatalogSetupSource } from '../catalogSetupLogic'
import { useSetupWithPostHogAIGate } from './useSetupWithPostHogAIGate'

export function SetupWithPostHogAIButton({
    source,
    type = 'primary',
}: {
    source: CatalogSetupSource
    type?: LemonButtonProps['type']
}): JSX.Element {
    const consentGate = useSetupWithPostHogAIGate(source)

    return (
        // `ignoreDismissal` keeps the popover reachable after a previous dismissal, so a click without
        // consent always has a way to grant it.
        <AIConsentPopoverWrapper ignoreDismissal {...consentGate.popover}>
            <LemonButton
                type={type}
                icon={<IconSparkles />}
                sideIcon={null}
                onClick={consentGate.onClick}
                // pinned: data-attr values feed autocapture dashboards
                data-attr={`data-catalog-setup-with-ai-${source}`}
            >
                Set up with PostHog AI
            </LemonButton>
        </AIConsentPopoverWrapper>
    )
}

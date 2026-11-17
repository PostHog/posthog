import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { CatalogSetupSource } from '../catalogSetupLogic'
import { useSetupWithPostHogAIGate } from './useSetupWithPostHogAIGate'

export function QuillSetupWithPostHogAIButton({
    source,
    size,
}: {
    source: CatalogSetupSource
    size?: 'default' | 'sm'
}): JSX.Element {
    const consentGate = useSetupWithPostHogAIGate(source)

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

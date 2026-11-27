import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { useAIConsentGate } from './useAIConsentGate'

export function QuillRunMetricWithAIButton({
    onRun,
    disabledReason,
}: {
    onRun: () => void
    disabledReason?: string
}): JSX.Element {
    const consentGate = useAIConsentGate(onRun)

    return (
        <AIConsentPopoverWrapper ignoreDismissal {...consentGate.popover}>
            <Button
                variant="primary"
                onClick={consentGate.onClick}
                disabledReason={disabledReason}
                data-attr="data-catalog-run-metric-with-ai"
            >
                <IconSparkles />
                Run with AI
            </Button>
        </AIConsentPopoverWrapper>
    )
}

import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

export function QuillRunMetricWithAIButton({
    onRun,
    disabledReason,
}: {
    onRun: () => void
    disabledReason?: string
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)

    return (
        <AIConsentPopoverWrapper onApprove={onRun} ignoreDismissal>
            <Button
                variant="primary"
                onClick={() => dataProcessingAccepted && onRun()}
                disabledReason={disabledReason}
                data-attr="data-catalog-run-metric-with-ai"
            >
                <IconSparkles />
                Run with AI
            </Button>
        </AIConsentPopoverWrapper>
    )
}

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { EvalSuggestionDismissReasonEnumApi } from '../../generated/api.schemas'

const DISMISS_REASONS: { reason: EvalSuggestionDismissReasonEnumApi; label: string }[] = [
    { reason: 'not_relevant', label: 'Not relevant' },
    { reason: 'already_covered', label: 'Already covered' },
    { reason: 'too_noisy', label: 'Too noisy' },
    { reason: 'fixed_cause', label: 'Fixed the cause' },
]

export function EvaluationSuggestionDismissMenu({
    loading,
    disabledReason,
    onDismiss,
}: {
    loading: boolean
    disabledReason: string | null
    onDismiss: (reason: EvalSuggestionDismissReasonEnumApi | null) => void
}): JSX.Element {
    return (
        <LemonMenu
            items={[
                {
                    title: 'Why dismiss it?',
                    items: DISMISS_REASONS.map(({ reason, label }) => ({ label, onClick: () => onDismiss(reason) })),
                },
                { items: [{ label: 'Dismiss without a reason', onClick: () => onDismiss(null) }] },
            ]}
        >
            <LemonButton
                type="secondary"
                size="small"
                loading={loading}
                disabledReason={disabledReason}
                data-attr="eval-suggestion-dismiss"
            >
                Dismiss
            </LemonButton>
        </LemonMenu>
    )
}

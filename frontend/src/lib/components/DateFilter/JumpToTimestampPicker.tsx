import { LemonButton } from '@posthog/lemon-ui'

import { JumpToTimestampForm } from './JumpToTimestampForm'

export function JumpToTimestampPicker({
    onApply,
    onClose,
}: {
    onApply: (dateFrom: string, dateTo: string) => void
    onClose: () => void
}): JSX.Element {
    return (
        <div className="w-80 p-2" data-attr="jump-to-timestamp-picker">
            <JumpToTimestampForm onSubmit={onApply}>
                {({ dateRange, submit }) => (
                    <div className="flex justify-between mt-3">
                        <LemonButton size="small" type="secondary" onClick={onClose}>
                            Back
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            disabledReason={!dateRange ? 'Enter a valid timestamp' : undefined}
                            onClick={submit}
                            data-attr="jump-to-timestamp-apply"
                        >
                            Apply
                        </LemonButton>
                    </div>
                )}
            </JumpToTimestampForm>
        </div>
    )
}

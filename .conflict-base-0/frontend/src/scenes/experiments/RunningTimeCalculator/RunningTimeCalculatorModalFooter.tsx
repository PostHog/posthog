import { LemonButton } from 'lib/lemon-ui/LemonButton'

export const RunningTimeCalculatorModalFooter = ({
    onClose,
    onSave,
    disabled = false,
}: {
    onClose: () => void
    onSave: () => void
    disabled?: boolean
}): JSX.Element => {
    return (
        <div className="flex items-center w-full">
            <div className="flex items-center gap-2 ml-auto">
                <LemonButton form="edit-experiment-metric-form" type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    form="edit-experiment-metric-form"
                    onClick={onSave}
                    type="primary"
                    disabledReason={disabled ? 'Calculation required before saving' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

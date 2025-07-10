import { LemonButton } from 'lib/lemon-ui/LemonButton'

export const RunningTimeCalculatorModalFooter = ({
    onClose,
    onSave,
}: {
    onClose: () => void
    onSave: () => void
}): JSX.Element => {
    return (
        <div className="flex w-full items-center">
            <div className="ml-auto flex items-center gap-2">
                <LemonButton form="edit-experiment-metric-form" type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton form="edit-experiment-metric-form" onClick={onSave} type="primary">
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

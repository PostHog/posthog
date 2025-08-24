import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function DashboardSaveButton({
    dashboardHasChanges,
    dashboardLoading,
    onSave,
    disabled,
}: {
    dashboardHasChanges: boolean
    dashboardLoading: boolean
    onSave: () => void
    disabled?: boolean
}): JSX.Element {
    const isDisabled = disabled || !dashboardHasChanges

    return (
        <LemonButton
            type="primary"
            data-attr="save-dashboard"
            onClick={onSave}
            disabledReason={isDisabled ? (dashboardHasChanges ? 'Dashboard is loading...' : undefined) : undefined}
            loading={dashboardLoading}
        >
            {isDisabled && !dashboardLoading ? 'No changes' : 'Save'}
        </LemonButton>
    )
}

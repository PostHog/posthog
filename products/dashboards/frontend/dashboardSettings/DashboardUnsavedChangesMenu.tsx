import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dashboardUnsavedChangesActions } from './dashboardUnsavedChangesActions'

export function DashboardUnsavedChangesMenu(): JSX.Element | null {
    const {
        dashboardSettingsState,
        layoutEditMode,
        canEditDashboard,
        dashboardSettingsChanges,
        dashboardFiltersSaving,
        showApplyFiltersBanner,
        loadingPreview,
    } = useValues(dashboardLogic)
    const { previewDashboardChanges, discardDashboardChanges, saveDashboardChanges } = useActions(dashboardLogic)

    if (dashboardSettingsState !== 'unsavedChanges') {
        return null
    }

    const changedCount = dashboardSettingsChanges.length
    const actions = dashboardUnsavedChangesActions({
        layoutEditMode,
        canEditDashboard,
        showApplyFiltersBanner,
        loadingPreview,
        dashboardFiltersSaving,
        discard: discardDashboardChanges,
        preview: previewDashboardChanges,
        save: saveDashboardChanges,
    })
    const keepActions = actions.filter((action) => action.key !== 'discard')
    const discard = actions.find((action) => action.key === 'discard')

    return (
        <DropdownMenu modal={false}>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        loading={dashboardFiltersSaving}
                        tooltip={
                            // Metric variable values come from queries over customer data, so copying them captures no text.
                            <ul className="ph-no-capture flex flex-col gap-1">
                                {dashboardSettingsChanges.map((change, index) => (
                                    <li key={`${change.label}-${index}`}>
                                        <span className="font-medium">{change.label}:</span>{' '}
                                        {change.value.length ? change.value.join(', ') : 'Default'}
                                    </li>
                                ))}
                            </ul>
                        }
                    />
                }
                data-attr="dashboard-filters-unsaved"
            >
                <span className="size-2 shrink-0 animate-pulse rounded-full bg-(--primary) motion-reduce:animate-none" />
                <span className="whitespace-nowrap">
                    {changedCount} unsaved {changedCount === 1 ? 'change' : 'changes'}
                </span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {keepActions.map((action) => (
                    <DropdownMenuItem
                        key={action.key}
                        disabledReason={action.disabledReason}
                        tooltip={action.tooltip}
                        onClick={action.onClick}
                        data-attr={action.dataAttr}
                    >
                        {action.label}
                    </DropdownMenuItem>
                ))}
                {discard && (
                    <>
                        {keepActions.length > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuItem
                            variant="destructive"
                            disabledReason={discard.disabledReason}
                            tooltip={discard.tooltip}
                            onClick={discard.onClick}
                            data-attr={discard.dataAttr}
                        >
                            {discard.label}
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

import { useActions, useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardSettingsChangesTooltip } from './DashboardSettingsChangesTooltip'

export function QuillDashboardUnsavedChangesActions(): JSX.Element | null {
    const {
        dashboardSettingsState,
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

    const changeSummary = `${dashboardSettingsChanges.length} unsaved ${dashboardSettingsChanges.length === 1 ? 'filter' : 'filters'}`
    const previewItem = (
        <DropdownMenuItem
            onClick={previewDashboardChanges}
            disabledReason={loadingPreview ? 'Previewing unsaved filters' : undefined}
            description="Update the data without saving the filters"
            data-attr="dashboard-apply-filters"
        >
            Preview
        </DropdownMenuItem>
    )

    return (
        <span data-attr="dashboard-filters-unsaved" className="flex items-center gap-2">
            {canEditDashboard ? (
                <ButtonGroup>
                    <DashboardSettingsChangesTooltip changes={dashboardSettingsChanges} title="Unsaved changes">
                        <Button
                            variant="primary"
                            onClick={saveDashboardChanges}
                            loading={dashboardFiltersSaving}
                            aria-label={`Save filters, ${changeSummary}`}
                            data-attr="dashboard-save-filters"
                        >
                            Save filters
                        </Button>
                    </DashboardSettingsChangesTooltip>
                    {showApplyFiltersBanner && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={<Button variant="primary" size="icon" aria-label="More save options" />}
                            >
                                <IconChevronDown />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">{previewItem}</DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </ButtonGroup>
            ) : (
                showApplyFiltersBanner && (
                    <Button
                        variant="outline"
                        onClick={previewDashboardChanges}
                        loading={loadingPreview}
                        data-attr="dashboard-apply-filters"
                    >
                        Preview
                    </Button>
                )
            )}
            <Button
                variant="outline"
                size="icon"
                aria-label="Discard filter changes"
                tooltip="Discard filter changes"
                disabledReason={dashboardFiltersSaving ? 'Dashboard filters are saving' : undefined}
                onClick={discardDashboardChanges}
                data-attr="dashboard-edit-mode-discard"
            >
                <IconX />
            </Button>
        </span>
    )
}

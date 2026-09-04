import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { dashboardLogic } from './dashboardLogic'
import { DashboardSettingsChangesTooltip } from './DashboardSettingsChangesTooltip'

export function DashboardUnsavedChangesIndicator(): JSX.Element | null {
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
    const discardDataAttr = layoutEditMode ? 'dashboard-discard-filters' : 'dashboard-edit-mode-discard'

    return (
        <span
            data-attr="dashboard-filters-unsaved"
            className="flex max-w-full items-center gap-1.5 rounded-full border border-warning bg-warning-highlight py-0.5 pl-2.5 pr-1 text-xs font-semibold text-warning"
        >
            <DashboardSettingsChangesTooltip changes={dashboardSettingsChanges} title="Unsaved changes">
                <LemonButton
                    type="tertiary"
                    size="small"
                    noPadding
                    className="text-inherit"
                    aria-label="Show dashboard changes"
                >
                    <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 animate-pulse motion-reduce:animate-none rounded-full bg-warning" />
                        <span className="@max-lg/dashboard-filters:hidden whitespace-nowrap">
                            {`${changedCount} unsaved ${changedCount === 1 ? 'change' : 'changes'}`}
                        </span>
                        <span className="@min-lg/dashboard-filters:hidden whitespace-nowrap">
                            {`${changedCount} unsaved`}
                        </span>
                        <IconInfo className="text-sm" />
                    </span>
                </LemonButton>
            </DashboardSettingsChangesTooltip>
            <span className="flex items-center gap-1.5 @max-lg/dashboard-filters:hidden">
                <span className="h-4 border-l border-warning" />
                <span className="flex items-center gap-1.5">
                    <LemonButton
                        data-attr={discardDataAttr}
                        type="tertiary"
                        size="small"
                        disabledReason={dashboardFiltersSaving ? 'Dashboard changes are saving' : undefined}
                        tooltip="Restore the settings saved to this dashboard."
                        onClick={discardDashboardChanges}
                    >
                        Discard
                    </LemonButton>
                    <span className="h-4 border-l border-warning" />
                    {showApplyFiltersBanner && (
                        <>
                            <LemonButton
                                data-attr="dashboard-apply-filters"
                                type="tertiary"
                                size="small"
                                disabledReason={loadingPreview ? 'Dashboard preview in progress' : undefined}
                                tooltip="Update the dashboard data with these unsaved filters. This does not save them."
                                onClick={previewDashboardChanges}
                            >
                                {loadingPreview ? 'Previewing' : 'Preview'}
                            </LemonButton>
                            <span className="h-4 border-l border-warning" />
                        </>
                    )}
                    {canEditDashboard && (
                        <LemonButton
                            data-attr="dashboard-save-filters"
                            type="tertiary"
                            size="small"
                            loading={dashboardFiltersSaving}
                            tooltip="Save these changes as the dashboard default."
                            onClick={saveDashboardChanges}
                        >
                            Save changes
                        </LemonButton>
                    )}
                </span>
            </span>
            <LemonMenu
                items={[
                    {
                        label: 'Discard',
                        disabledReason: dashboardFiltersSaving ? 'Dashboard changes are saving' : undefined,
                        onClick: discardDashboardChanges,
                    },
                    ...(showApplyFiltersBanner
                        ? [
                              {
                                  label: loadingPreview ? 'Previewing' : 'Preview',
                                  disabledReason: loadingPreview ? 'Dashboard preview in progress' : undefined,
                                  onClick: previewDashboardChanges,
                              },
                          ]
                        : []),
                    ...(canEditDashboard
                        ? [
                              {
                                  label: 'Save changes',
                                  disabledReason: dashboardFiltersSaving ? 'Dashboard changes are saving' : undefined,
                                  onClick: saveDashboardChanges,
                              },
                          ]
                        : []),
                ]}
                placement="bottom-end"
            >
                <LemonButton
                    className="@min-lg/dashboard-filters:hidden"
                    type="tertiary"
                    size="small"
                    loading={dashboardFiltersSaving}
                >
                    Actions
                </LemonButton>
            </LemonMenu>
        </span>
    )
}

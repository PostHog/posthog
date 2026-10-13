import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

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
    const changeSummary = `${changedCount} unsaved ${changedCount === 1 ? 'filter' : 'filters'}`
    const discardDataAttr = layoutEditMode ? 'dashboard-discard-filters' : 'dashboard-edit-mode-discard'
    const actions = [
        {
            key: 'discard',
            label: 'Discard',
            dataAttr: discardDataAttr,
            disabledReason: dashboardFiltersSaving ? 'Dashboard filters are saving' : undefined,
            tooltip: 'Restore the settings saved to this dashboard.',
            onClick: discardDashboardChanges,
            loading: false,
        },
        ...(showApplyFiltersBanner
            ? [
                  {
                      key: 'preview',
                      label: loadingPreview ? 'Previewing' : 'Preview',
                      dataAttr: 'dashboard-apply-filters',
                      disabledReason: loadingPreview ? 'Previewing unsaved filters' : undefined,
                      tooltip: 'Update the dashboard data with these unsaved filters. This does not save them.',
                      onClick: previewDashboardChanges,
                      loading: false,
                  },
              ]
            : []),
        ...(canEditDashboard
            ? [
                  {
                      key: 'save',
                      label: 'Save filters',
                      dataAttr: 'dashboard-save-filters',
                      disabledReason: undefined,
                      tooltip: 'Save these changes as the dashboard default.',
                      onClick: saveDashboardChanges,
                      loading: dashboardFiltersSaving,
                  },
              ]
            : []),
    ]

    return (
        <span
            data-attr="dashboard-filters-unsaved"
            className="flex max-w-full items-center rounded border border-warning bg-warning-highlight text-xs font-semibold text-warning"
        >
            <DashboardSettingsChangesTooltip changes={dashboardSettingsChanges} title="Unsaved changes">
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="rounded-l text-inherit"
                    aria-label={`Show ${changeSummary}`}
                >
                    <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 animate-pulse motion-reduce:animate-none rounded-full bg-warning" />
                        <span className="@max-lg/dashboard-filters:hidden whitespace-nowrap">{changeSummary}</span>
                        <span className="@min-lg/dashboard-filters:hidden whitespace-nowrap">
                            {`${changedCount} unsaved`}
                        </span>
                        <IconInfo className="text-sm" />
                    </span>
                </LemonButton>
            </DashboardSettingsChangesTooltip>
            <span className="flex items-center @max-lg/dashboard-filters:hidden">
                {actions.map((action, index) => (
                    <LemonButton
                        key={action.key}
                        data-attr={action.dataAttr}
                        type="tertiary"
                        size="small"
                        className={`border-l border-warning ${index === actions.length - 1 ? 'rounded-r' : 'rounded-none'}`}
                        disabledReason={action.disabledReason}
                        tooltip={action.tooltip}
                        onClick={action.onClick}
                        loading={action.loading}
                    >
                        {action.label}
                    </LemonButton>
                ))}
            </span>
            <LemonMenu
                items={actions.map((action) => ({
                    key: action.key,
                    label: action.label,
                    'data-attr': action.dataAttr,
                    disabledReason: action.disabledReason,
                    tooltip: action.tooltip,
                    onClick: action.onClick,
                }))}
                placement="bottom-end"
            >
                <LemonButton
                    className="@min-lg/dashboard-filters:hidden rounded-r border-l border-warning"
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

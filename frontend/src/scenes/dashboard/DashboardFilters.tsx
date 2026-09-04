import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement } from '~/types'

import { DashboardEditBar } from './DashboardEditBar'
import { dashboardLogic } from './dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from './DashboardReloadAction'
import { DashboardSettingsChangesTooltip } from './DashboardSettingsChangesTooltip'

function UnsavedFiltersIndicator(): JSX.Element | null {
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
                    {showApplyFiltersBanner && !layoutEditMode && (
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
                    ...(showApplyFiltersBanner && !layoutEditMode
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

interface DashboardFilterBarProps {
    backTo?: { url: string; name: string }
}

export function DashboardFilterBar({ backTo }: DashboardFilterBarProps): JSX.Element {
    const { placement, dashboard, dashboardMode, hasVariables } = useValues(dashboardLogic)
    return (
        <div className="@container/dashboard-filters flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-wrap gap-x-2 gap-y-2 justify-between items-start">
                <div className="flex min-w-0 flex-1 flex-col gap-2 @2xl/dashboard-filters:flex-row @2xl/dashboard-filters:justify-between items-start @4xl/dashboard-filters:items-center">
                    <div className="flex min-w-0 flex-1 flex-wrap gap-4 items-center">
                        {![
                            DashboardPlacement.Public,
                            DashboardPlacement.Export,
                            DashboardPlacement.FeatureFlag,
                            DashboardPlacement.Group,
                            DashboardPlacement.DataOps,
                            DashboardPlacement.Builtin,
                        ].includes(placement) &&
                            dashboard && <DashboardEditBar />}
                        <UnsavedFiltersIndicator />
                    </div>
                </div>
                {![DashboardPlacement.Export, DashboardPlacement.Builtin].includes(placement) && (
                    <div
                        className={clsx(
                            'flex flex-col @4xl/dashboard-filters:flex-row items-end @4xl/dashboard-filters:items-center gap-4 dashoard-items-actions',
                            'min-w-0 @max-4xl/dashboard-filters:basis-full @max-4xl/dashboard-filters:w-full @max-4xl/dashboard-filters:ml-0 shrink-0 @4xl/dashboard-filters:ml-auto',
                            {
                                'mt-7': hasVariables,
                            }
                        )}
                    >
                        <div className={`left-item ${placement === DashboardPlacement.Public ? 'text-right' : ''}`}>
                            {[DashboardPlacement.Public].includes(placement) ? (
                                <LastRefreshText />
                            ) : !(dashboardMode === DashboardMode.Edit) ? (
                                <DashboardReloadAction />
                            ) : null}
                        </div>
                        {[
                            DashboardPlacement.FeatureFlag,
                            DashboardPlacement.Group,
                            DashboardPlacement.DataOps,
                        ].includes(placement) &&
                            dashboard?.id && (
                                <LemonMenu
                                    items={[
                                        {
                                            label:
                                                placement === DashboardPlacement.Group
                                                    ? 'Edit dashboard template'
                                                    : 'Edit dashboard',
                                            to: backTo
                                                ? `${urls.dashboard(dashboard.id)}?backUrl=${encodeURIComponent(backTo.url)}&backName=${encodeURIComponent(backTo.name)}`
                                                : urls.dashboard(dashboard.id),
                                        },
                                    ]}
                                    placement="bottom-end"
                                    fallbackPlacements={['bottom-start', 'bottom']}
                                >
                                    <LemonButton size="small" icon={<IconEllipsis className="text-secondary" />} />
                                </LemonMenu>
                            )}
                    </div>
                )}
            </div>
        </div>
    )
}

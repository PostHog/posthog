import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement } from '~/types'

import { DashboardEditBar } from './DashboardEditBar'
import type { DashboardFilterChange } from './dashboardFilterChanges'
import { DashboardFilterChangesTooltip } from './DashboardFilterChangesTooltip'
import { dashboardLogic, RefreshDashboardItemsAction } from './dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from './DashboardReloadAction'
import { DashboardTemporaryFiltersNotice } from './DashboardTemporaryFiltersNotice'

function formatVariableValue(variable: { isNull?: boolean; value?: unknown } | undefined): string | undefined {
    if (variable?.isNull) {
        return 'null'
    }
    if (variable?.value == null) {
        return undefined
    }
    return String(variable.value)
}

function UnsavedFiltersIndicator(): JSX.Element | null {
    const {
        dashboardMode,
        filterEditModeActive,
        hasIntermittentFilters,
        isTemporaryFilterView,
        layoutEditMode,
        canEditDashboard,
        changedFilterCount,
        filterChanges,
        filtersDirty,
        variablesDirty,
        dashboard,
        effectiveDashboardVariableOverrides,
        variables,
        dashboardFiltersSaving,
        showApplyFiltersBanner,
        loadingPreview,
    } = useValues(dashboardLogic)
    const {
        applyFilters,
        discardDashboardFilters,
        refreshDashboardItems,
        resetUrlVariables,
        saveDashboardFilters,
        saveEditModeChanges,
    } = useActions(dashboardLogic)
    const hasUnsavedChanges = filtersDirty || variablesDirty
    if (
        !canEditDashboard ||
        !hasUnsavedChanges ||
        (!filterEditModeActive && dashboardMode !== DashboardMode.Edit && !hasIntermittentFilters) ||
        isTemporaryFilterView
    ) {
        return null
    }

    const discardAction =
        variablesDirty && !filtersDirty
            ? () => {
                  resetUrlVariables()
                  refreshDashboardItems({ action: RefreshDashboardItemsAction.Preview, forceRefresh: false })
              }
            : discardDashboardFilters
    const saveAction = variablesDirty && !filtersDirty ? saveEditModeChanges : saveDashboardFilters
    const changeLabel = variablesDirty && !filtersDirty ? 'unsaved variables' : 'unsaved filters'
    const changes: DashboardFilterChange[] =
        variablesDirty && !filtersDirty
            ? Object.values(effectiveDashboardVariableOverrides).map((variable) => {
                  const persistedVariable = dashboard?.persisted_variables?.[variable.variableId]
                  const dashboardVariable = variables.find((candidate) => candidate.id === variable.variableId)
                  const previous =
                      persistedVariable ??
                      (dashboardVariable
                          ? { value: dashboardVariable.default_value, isNull: dashboardVariable.isNull }
                          : undefined)
                  return {
                      label: variable.code_name,
                      previousValue: formatVariableValue(previous),
                      value: formatVariableValue(variable),
                      status: previous ? 'changed' : 'new',
                  }
              })
            : filterChanges
    const changedCount = changes.length
    const discardDataAttr = layoutEditMode ? 'dashboard-discard-filters' : 'dashboard-edit-mode-discard'

    return (
        <span
            data-attr="dashboard-filters-unsaved"
            className="flex max-w-full items-center gap-1.5 rounded-full border border-warning bg-warning-highlight py-0.5 pl-2.5 pr-1 text-xs font-semibold text-warning"
        >
            <DashboardFilterChangesTooltip changes={changes} title="Unsaved changes">
                <button
                    type="button"
                    className="flex items-center gap-1.5 border-0 bg-transparent p-0 text-left text-inherit cursor-pointer"
                    aria-label="Show filter changes"
                >
                    <span className="h-2 w-2 animate-pulse rounded-full bg-warning" />
                    <span className="@max-lg/dashboard-filters:hidden whitespace-nowrap">
                        {`${variablesDirty && !filtersDirty ? changedCount : changedFilterCount} ${changeLabel}`}
                    </span>
                    <span className="@min-lg/dashboard-filters:hidden whitespace-nowrap">
                        {`${variablesDirty && !filtersDirty ? changedCount : changedFilterCount} unsaved`}
                    </span>
                    <IconInfo className="cursor-pointer text-sm" />
                </button>
            </DashboardFilterChangesTooltip>
            <span className="flex items-center gap-1.5 @max-lg/dashboard-filters:hidden">
                <span className="h-4 border-l border-warning" />
                <span className="flex items-center gap-1.5">
                    <LemonButton
                        data-attr={discardDataAttr}
                        type="tertiary"
                        size="small"
                        tooltip="Restore the filters saved to this dashboard."
                        onClick={discardAction}
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
                                loading={loadingPreview}
                                tooltip="Update the dashboard data with these unsaved filters. This does not save them."
                                onClick={applyFilters}
                            >
                                Preview
                            </LemonButton>
                            <span className="h-4 border-l border-warning" />
                        </>
                    )}
                    <LemonButton
                        data-attr="dashboard-save-filters"
                        type="tertiary"
                        size="small"
                        loading={dashboardFiltersSaving}
                        tooltip="Save these filters as the dashboard default."
                        onClick={saveAction}
                    >
                        {variablesDirty && !filtersDirty ? 'Save changes' : 'Save filters'}
                    </LemonButton>
                </span>
            </span>
            <LemonMenu
                items={[
                    {
                        label: 'Discard',
                        onClick: discardAction,
                    },
                    ...(showApplyFiltersBanner && !layoutEditMode
                        ? [
                              {
                                  label: 'Preview',
                                  onClick: applyFilters,
                              },
                          ]
                        : []),
                    {
                        label: 'Save filters',
                        onClick: saveAction,
                    },
                ]}
                placement="bottom-end"
            >
                <LemonButton
                    className="@min-lg/dashboard-filters:hidden"
                    type="tertiary"
                    size="small"
                    loading={dashboardFiltersSaving || loadingPreview}
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
                        <DashboardTemporaryFiltersNotice />
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

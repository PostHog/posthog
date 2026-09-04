import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import type { DashboardFilterChange } from './dashboardFilterChanges'
import { DashboardFilterChangesTooltip } from './DashboardFilterChangesTooltip'
import { dashboardLogic, RefreshDashboardItemsAction } from './dashboardLogic'

export function DashboardTemporaryFiltersNotice(): JSX.Element | null {
    const { cancellingPreview, filterChanges, hasUrlFilters, isTemporaryFilterView, urlVariables } =
        useValues(dashboardLogic)
    const { refreshDashboardItems, resetUrlVariables, setDashboardMode } = useActions(dashboardLogic)

    if (!isTemporaryFilterView) {
        return null
    }

    const hasUrlVariables = Object.keys(urlVariables).length > 0
    const label = hasUrlFilters ? 'Temporary filters' : 'Temporary variables'
    const changes: DashboardFilterChange[] = [
        ...filterChanges,
        ...(hasUrlVariables
            ? [
                  {
                      label: 'SQL variable',
                      value: Object.values(urlVariables).map((variable) =>
                          variable.isNull ? `${variable.code_name}: null` : `${variable.code_name}: ${variable.value}`
                      ),
                      status: 'new' as const,
                  },
              ]
            : []),
    ]
    const clear = hasUrlFilters
        ? () => setDashboardMode(null, DashboardEventSource.DashboardHeaderOverridesBanner)
        : () => {
              resetUrlVariables()
              refreshDashboardItems({ action: RefreshDashboardItemsAction.Preview, forceRefresh: false })
          }

    return (
        <span
            data-attr="dashboard-temporary-filters"
            className="mt-1 flex max-w-full flex-nowrap items-center gap-1.5 rounded-full border border-warning bg-warning-highlight py-0.5 pl-2.5 pr-1 text-xs text-warning"
        >
            <DashboardFilterChangesTooltip changes={changes} title="Temporary changes">
                <button
                    type="button"
                    className="flex min-w-0 items-center gap-1.5 border-0 bg-transparent p-0 text-left text-inherit cursor-pointer"
                    aria-label="Show temporary filter changes"
                >
                    <span className="h-2 w-2 shrink-0 rounded-full bg-warning" />
                    <span className="shrink-0 font-semibold">{label}</span>
                    <IconInfo className="shrink-0 cursor-pointer text-sm" />
                    <span className="@max-4xl/dashboard-filters:hidden text-secondary">
                        Only you see these filters.
                    </span>
                </button>
            </DashboardFilterChangesTooltip>
            <LemonButton
                type="tertiary"
                size="small"
                className="font-semibold text-warning"
                tooltip={`Clear ${hasUrlVariables ? 'temporary variables' : 'temporary filters'}`}
                loading={cancellingPreview}
                onClick={clear}
            >
                Clear
            </LemonButton>
        </span>
    )
}

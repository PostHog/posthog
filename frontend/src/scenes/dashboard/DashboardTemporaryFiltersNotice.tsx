import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import { DashboardFilterChangesTooltip } from './DashboardFilterChangesTooltip'
import { dashboardLogic } from './dashboardLogic'

export function DashboardTemporaryFiltersNotice(): JSX.Element | null {
    const { cancellingPreview, filterChanges, isTemporaryFilterView } = useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)

    if (!isTemporaryFilterView) {
        return null
    }

    return (
        <span
            data-attr="dashboard-temporary-filters"
            className="mt-1 flex max-w-full flex-nowrap items-center gap-1.5 rounded-full border border-warning bg-warning-highlight py-0.5 pl-2.5 pr-1 text-xs text-warning"
        >
            <DashboardFilterChangesTooltip changes={filterChanges}>
                <button
                    type="button"
                    className="flex min-w-0 items-center gap-1.5 border-0 bg-transparent p-0 text-left text-inherit cursor-pointer"
                    aria-label="Show temporary filter changes"
                >
                    <span className="h-2 w-2 shrink-0 rounded-full bg-warning" />
                    <span className="shrink-0 font-semibold">Temporary filters</span>
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
                tooltip="Clear temporary filters"
                loading={cancellingPreview}
                onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderOverridesBanner)}
            >
                Clear
            </LemonButton>
        </span>
    )
}

import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import { DashboardControlSlot } from './DashboardControlSlot'

/** `withShortcut` registers the date filter keybind. Pass it to one copy only, because a second registration conflicts. */
export function DashboardDateFilter({ withShortcut = false }: { withShortcut?: boolean }): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setDates, setDashboardEditing } = useActions(dashboardLogic)
    const quillSurface = useQuillSurface()

    const dateFilter = (
        <DateFilter
            showCustom
            showExplicitDateToggle
            allowTimePrecision
            allowFixedRangeWithTime
            dateFrom={effectiveEditBarFilters.date_from}
            dateTo={effectiveEditBarFilters.date_to}
            explicitDate={effectiveEditBarFilters.explicitDate}
            onChange={(from_date, to_date, explicitDate) => {
                if (!dashboardEditing) {
                    setDashboardEditing(true, DashboardEventSource.DashboardFilters)
                }
                setDates(from_date, to_date, explicitDate)
            }}
            makeLabel={(key) =>
                quillSurface ? (
                    <span className="hide-when-small">{key}</span>
                ) : (
                    <>
                        <IconCalendar />
                        <span className="hide-when-small"> {key}</span>
                    </>
                )
            }
        />
    )

    return (
        <DashboardControlSlot
            control="dateRange"
            hasValue={!!effectiveEditBarFilters.date_from || !!effectiveEditBarFilters.date_to}
            className="min-w-0"
        >
            {withShortcut ? (
                <Shortcut
                    name="DashboardDateFilter"
                    keybind={[keyBinds.dateFilter]}
                    intent="Date filter"
                    interaction="click"
                    scope={Scene.Dashboard}
                >
                    {dateFilter}
                </Shortcut>
            ) : (
                dateFilter
            )}
        </DashboardControlSlot>
    )
}

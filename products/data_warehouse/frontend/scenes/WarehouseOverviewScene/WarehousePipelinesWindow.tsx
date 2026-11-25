import { useActions, useValues } from 'kea'

import { type SegmentedOption, WarehouseSegmentedControl } from '../WarehouseConsole/WarehouseSegmentedControl'
import { warehouseOverviewLogic } from './warehouseOverviewLogic'
import type { JobStatsDays } from './warehouseOverviewStats'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

const WINDOW_OPTIONS: SegmentedOption<`${JobStatsDays}`>[] = [
    { value: '1', label: '24 h', 'data-attr': 'warehouse-overview-window-1' },
    { value: '7', label: '7 d', 'data-attr': 'warehouse-overview-window-7' },
    { value: '30', label: '30 d', 'data-attr': 'warehouse-overview-window-30' },
]

/** The time window of the run statistics. */
export function WarehousePipelinesWindow(): JSX.Element {
    const { jobStatsDays, jobStatsLoading } = useValues(warehouseOverviewLogic)
    const { setJobStatsDays } = useActions(warehouseOverviewLogic)

    return (
        <WarehouseSegmentedControl
            value={`${jobStatsDays}`}
            options={WINDOW_OPTIONS}
            onChange={(value) => setJobStatsDays(Number(value) as JobStatsDays)}
            label="Run statistics window"
            disabled={jobStatsLoading}
        />
    )
}

import { useActions, useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseRunBars } from '../WarehouseConsole/WarehouseRunBars'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { type SegmentedOption, WarehouseSegmentedControl } from '../WarehouseConsole/WarehouseSegmentedControl'
import type { HistoryDays } from './pipelineHealthStats'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

const WINDOW_OPTIONS: SegmentedOption<`${HistoryDays}`>[] = [
    { value: '7', label: '7 d', 'data-attr': 'warehouse-pipeline-health-window-7' },
    { value: '30', label: '30 d', 'data-attr': 'warehouse-pipeline-health-window-30' },
]

function LegendItem({ color, label }: { color: string; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5">
            <span className={`size-2 rounded-sm ${color}`} aria-hidden />
            {label}
        </span>
    )
}

/** Copy, register and backfill runs that finished each day, succeeded against failed. */
export function WarehousePipelineRuns(): JSX.Element {
    const { landingHistory, historyBuckets, historyDays, historyEmpty, historyFailed, landingHistoryLoading } =
        useValues(warehousePipelineHealthLogic)
    const { setHistoryDays, retryHistory } = useActions(warehousePipelineHealthLogic)

    let content: JSX.Element
    if (!landingHistory) {
        content = historyFailed ? (
            <WarehouseResourceError
                title="Couldn't load run history"
                onRetry={retryHistory}
                data-attr="warehouse-pipeline-health-history-retry"
            />
        ) : (
            <Skeleton className="h-32 w-full" />
        )
    } else if (historyEmpty) {
        content = (
            <Text size="sm" variant="muted">
                No runs finished in this window
            </Text>
        )
    } else {
        content = (
            <div className="flex flex-col gap-2">
                <WarehouseRunBars
                    buckets={historyBuckets}
                    unit="day"
                    size="large"
                    data-attr="warehouse-pipeline-health-run-bars"
                />
                <Text size="xs" variant="muted" className="flex flex-wrap gap-x-4 gap-y-1" render={<div />}>
                    <LegendItem color="bg-[var(--success-foreground)]" label="Succeeded" />
                    <LegendItem color="bg-[var(--destructive-foreground)]" label="Failed" />
                </Text>
            </div>
        )
    }

    return (
        <WarehouseSection
            title="Warehouse runs"
            description="Copy, register and backfill runs that finished each day."
            data-attr="warehouse-pipeline-health-runs"
            controls={
                <WarehouseSegmentedControl
                    value={`${historyDays}`}
                    options={WINDOW_OPTIONS}
                    onChange={(value) => setHistoryDays(Number(value) as HistoryDays)}
                    label="Run history window"
                    disabled={landingHistoryLoading}
                />
            }
        >
            {content}
        </WarehouseSection>
    )
}

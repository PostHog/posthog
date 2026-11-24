import { useActions } from 'kea'

import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseDatasetStatusApi } from '../../generated/api.schemas'
import { formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseMeter } from '../WarehouseConsole/WarehouseMeter'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { formatDay } from './pipelineHealthStats'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

/** One dataset (events or persons) in the warehouse: its landing state, backfill progress and last failure. */
export function WarehousePipelineDatasetRow({
    label,
    dataset,
}: {
    label: string
    dataset: ManagedWarehouseDatasetStatusApi
}): JSX.Element {
    const { linkClicked } = useActions(warehousePipelineHealthLogic)
    const total = dataset.total_partitions
    const hasTotal = total !== null && total > 0
    const backfillOff = dataset.readiness_state === 'not_configured'
    const failure = dataset.last_error
        ? dataset.current_partition
            ? `${dataset.current_partition}: ${dataset.last_error}`
            : dataset.last_error
        : null

    return (
        <div
            className="flex flex-col gap-1.5 px-3 py-3"
            data-attr={`warehouse-pipeline-health-dataset-${label.toLowerCase()}`}
        >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Text size="sm" weight="semibold" className="w-16" render={<span />}>
                    {label}
                </Text>
                <WarehouseStatusBadge status={dataset.landing_state} />
                {backfillOff ? null : (
                    <Text size="xs" variant="muted" className="tabular-nums" render={<span />}>
                        {hasTotal
                            ? `${formatCount(dataset.completed_partitions)} of ${formatCount(total)} partitions`
                            : 'Calculating partitions'}
                    </Text>
                )}
                {dataset.latest_day_loaded ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        Loaded through {formatDay(dataset.latest_day_loaded)}
                    </Text>
                ) : null}
                {dataset.last_completed_at ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        Last completed <WarehouseTime iso={dataset.last_completed_at} />
                    </Text>
                ) : null}
            </div>
            {hasTotal && !backfillOff ? (
                <div className="max-w-md">
                    <WarehouseMeter used={dataset.completed_partitions} limit={total} label={`${label} backfill`} />
                </div>
            ) : null}
            {backfillOff ? (
                <Text size="xs" variant="muted">
                    Backfill is off, so history is not copied into your warehouse.{' '}
                    <LinkPrimitive
                        to={urls.warehouseSettings()}
                        onClick={() => linkClicked('settings')}
                        data-attr="warehouse-pipeline-health-backfill-settings"
                    >
                        Open Settings
                    </LinkPrimitive>
                </Text>
            ) : null}
            {failure ? (
                <Text size="xs" variant="destructive" className="truncate" title={failure}>
                    {failure}
                </Text>
            ) : null}
        </div>
    )
}

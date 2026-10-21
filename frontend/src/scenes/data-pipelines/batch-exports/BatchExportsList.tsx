import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { urls } from 'scenes/urls'

import type { BatchExportApi } from 'products/batch_exports/frontend/generated/api.schemas'

import { BATCH_EXPORT_ICON_MAP } from './BatchExportIcon'
import { batchExportsListLogic } from './batchExportsListLogic'
import {
    compareBatchExportScheduleStatus,
    getBatchExportScheduleStatus,
    humanizeBatchExportInterval,
    humanizeBatchExportName,
    normalizeBatchExportService,
} from './utils'

const columns: LemonTableColumn<BatchExportApi, any>[] = [
    {
        title: '',
        width: 0,
        render: function RenderIcon(_, batchExport) {
            return (
                <HogFunctionIcon
                    src={BATCH_EXPORT_ICON_MAP[normalizeBatchExportService(batchExport.destination.type)]}
                    size="small"
                />
            )
        },
    },
    {
        title: 'Name',
        sticky: true,
        key: 'name',
        dataIndex: 'name',
        sorter: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }),
        render: (_, batchExport) => (
            <LemonTableLink
                to={urls.batchExport(batchExport.id)}
                title={batchExport.name}
                description={humanizeBatchExportName(normalizeBatchExportService(batchExport.destination.type))}
            />
        ),
    },
    {
        title: 'Interval',
        key: 'interval',
        dataIndex: 'interval',
        width: 0,
        render: (_, batchExport) => (
            <span className="whitespace-nowrap">{humanizeBatchExportInterval(batchExport.interval)}</span>
        ),
    },
    createdAtColumn() as LemonTableColumn<BatchExportApi, any>,
    {
        title: 'Last 7 days',
        width: 0,
        render: (_, batchExport) => (
            <Link to={urls.batchExport(batchExport.id, 'metrics')}>
                <AppMetricsSparkline
                    logicKey={batchExport.id}
                    metricLabels={{ cancellation: 'Canceled' }}
                    metricColors={{ cancellation: 'warning' }}
                    forceParams={{
                        appSource: 'batch_export',
                        appSourceId: batchExport.id,
                        // Canceled runs report under the 'cancellation' kind. Without it, a week of
                        // cancellations reads as idle and this row disagrees with the metrics tab.
                        metricKind: ['success', 'failure', 'cancellation'],
                        breakdownBy: 'metric_kind',
                        interval: 'day',
                        dateFrom: '-7d',
                    }}
                />
            </Link>
        ),
    },
    {
        title: 'Status',
        key: 'paused',
        width: 0,
        sorter: compareBatchExportScheduleStatus,
        render: function RenderStatus(_, batchExport) {
            const status = getBatchExportScheduleStatus(batchExport)
            if (status === 'paused') {
                return <LemonTag type="default">Paused</LemonTag>
            }
            if (status === 'ended') {
                return (
                    <Tooltip title="This export is past its end date, so it will not run again.">
                        <LemonTag type="default">Ended</LemonTag>
                    </Tooltip>
                )
            }
            return <LemonTag type="success">Active</LemonTag>
        },
    },
]

export function BatchExportsList(): JSX.Element {
    const { batchExports, batchExportsLoading, filteredBatchExports, hiddenBatchExports, filters } =
        useValues(batchExportsListLogic)
    const { setFilters, resetFilters } = useActions(batchExportsListLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(search) => setFilters({ search })}
                />
                <div className="flex-1" />
                <LemonCheckbox
                    label="Show paused"
                    bordered
                    size="small"
                    checked={filters.showPaused}
                    onChange={(showPaused) => setFilters({ showPaused: showPaused || undefined })}
                />
            </div>

            <LemonTable
                dataSource={filteredBatchExports}
                // The sparkline loads once per row, so a row must keep its export across a sort or a search.
                rowKey="id"
                size="small"
                loading={batchExportsLoading}
                columns={columns}
                pagination={{ pageSize: 30 }}
                emptyState={
                    batchExports === null ? (
                        "Couldn't load batch exports. Refresh the page to try again."
                    ) : batchExports.length === 0 ? (
                        'No batch exports found'
                    ) : (
                        <>
                            No batch exports matching filters. <Link onClick={() => resetFilters()}>Clear filters</Link>
                        </>
                    )
                }
                footer={
                    hiddenBatchExports.length > 0 && (
                        <div className="p-3 text-secondary">
                            <span>{`${hiddenBatchExports.length} hidden.`}</span>{' '}
                            <Link
                                onClick={() => {
                                    resetFilters()
                                    setFilters({ showPaused: true })
                                }}
                            >
                                Show all
                            </Link>
                        </div>
                    )
                }
            />
        </div>
    )
}

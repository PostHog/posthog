import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { deadLetterQueueLogic } from './deadLetterQueueLogic'

// keep in sync with posthog/api/dead_letter_queue.py
const ROWS_LIMIT = 10

export function MetricsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { singleValueMetrics, tableMetrics, deadLetterQueueMetricsLoading, rowsPerMetric, filters } =
        useValues(deadLetterQueueLogic)
    const { loadDeadLetterQueueMetrics, loadMoreRows, setFilters } = useActions(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <br />
            <DateFilter
                dateTo={filters.before}
                dateFrom={filters.after}
                onChange={(from, to) => setFilters({ after: from || undefined, before: to || undefined })}
                allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                makeLabel={(key) => (
                    <>
                        <IconCalendar /> {key}
                    </>
                )}
            />

            <div className="mb-4 float-right">
                <LemonButton
                    icon={deadLetterQueueMetricsLoading ? <Spinner /> : <IconRefresh />}
                    onClick={loadDeadLetterQueueMetrics}
                    type="secondary"
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>

            <div className="flex deprecated-space-x-8 mb-4">
                {singleValueMetrics.map((row) => (
                    <div key={row.key} className="deprecated-space-y-1">
                        <div>{row.metric}</div>
                        <div className="text-2xl">{(row.value || '0').toLocaleString('en-US')}</div>
                    </div>
                ))}
            </div>

            {tableMetrics.map((row) => (
                <div key={row.key}>
                    <h2>{row.metric}</h2>
                    <LemonTable
                        columns={
                            row.subrows?.columns?.map((columnTitle, index) => ({
                                title: columnTitle,
                                dataIndex: `col${index}`,
                                className: 'whitespace-nowrap overflow-hidden text-ellipsis max-w-xs cursor-pointer',
                                render: (value: any) => (
                                    <span
                                        onClick={() => copyToClipboard(String(value), 'value')}
                                        title="Click to copy"
                                        className="hover:bg-gray-100 px-1 py-0.5 rounded"
                                    >
                                        {value}
                                    </span>
                                ),
                            })) || []
                        }
                        dataSource={
                            rowsPerMetric[row.key].map((rowData) => {
                                const rowObject: Record<string, any> = {}
                                rowData.forEach((value, index) => {
                                    rowObject[`col${index}`] = value
                                })
                                return rowObject
                            }) || []
                        }
                        loading={deadLetterQueueMetricsLoading}
                        defaultSorting={{
                            columnKey: 'value',
                            order: -1,
                        }}
                        embedded
                    />
                    <div className="flex justify-center m-4 text-center">
                        <LemonButton
                            disabledReason={rowsPerMetric[row.key].length % ROWS_LIMIT !== 0 && 'No more values'}
                            onClick={() => loadMoreRows(row.key)}
                        >
                            Load more values
                        </LemonButton>
                    </div>
                    <LemonDivider />
                </div>
            ))}
        </div>
    )
}

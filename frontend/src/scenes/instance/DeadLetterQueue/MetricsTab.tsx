import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'

import { deadLetterQueueLogic } from './deadLetterQueueLogic'

// keep in sync with posthog/api/dead_letter_queue.py
const ROWS_LIMIT = 10

export function MetricsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { singleValueMetrics, tableMetrics, deadLetterQueueMetricsLoading, rowsPerMetric } =
        useValues(deadLetterQueueLogic)
    const { loadDeadLetterQueueMetrics, loadMoreRows } = useActions(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <br />

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

            <div className="flex space-x-8 mb-4">
                {singleValueMetrics.map((row) => (
                    <div key={row.key} className="space-y-1">
                        <div>{row.metric}</div>
                        <div className="text-2xl">{(row.value || '0').toLocaleString('en-US')}</div>
                    </div>
                ))}
            </div>

            {tableMetrics.map((row) => (
                <div key={row.key}>
                    <h2>{row.metric}</h2>
                    <LemonTable
                        columns={[
                            {
                                title: row.subrows?.columns[0],
                                dataIndex: 'key',
                            },
                            {
                                title: row.subrows?.columns[1],
                                dataIndex: 'value',
                            },
                        ]}
                        dataSource={rowsPerMetric[row.key].map(([key, value]) => ({ key, value })) || []}
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

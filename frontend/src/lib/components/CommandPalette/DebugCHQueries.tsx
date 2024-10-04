import { IconCodeInsert, IconCopy } from '@posthog/icons'
import { ChartConfiguration, ChartDataset } from 'chart.js'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import { actions, afterMount, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Chart, ChartItem } from 'lib/Chart'
import { dayjs } from 'lib/dayjs'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { humanizeBytes } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { CodeSnippet, Language } from '../CodeSnippet'
import type { debugCHQueriesLogicType } from './DebugCHQueriesType'

export function openCHQueriesDebugModal(): void {
    LemonDialog.open({
        title: 'ClickHouse queries recently executed for this user',
        content: <DebugCHQueries />,
        primaryButton: null,
        width: 1600,
    })
}

export interface Stats {
    total_queries: number
    total_exceptions: number
    average_query_duration_ms: number | null
    max_query_duration_ms: number
    exception_percentage: number | null
}

interface DataPoint {
    hour: string
    successful_queries: number
    exceptions: number
    avg_response_time_ms: number
}

export interface Query {
    /** @example '2023-07-27T10:06:11' */
    timestamp: string
    query: string
    query_id: string
    exception: string
    /**
     * 1 means running, 2 means finished, 3 means errored before execution, 4 means errored during execution.
     *
     * @see `type` column in https://clickhouse.com/docs/en/operations/system-tables/query_log */
    status: 1 | 2 | 3 | 4
    execution_time: number
    path: string
    logComment: Record<string, unknown>
}

export interface DebugResponse {
    queries: Query[]
    stats: Stats
    hourly_stats: DataPoint[]
}

const debugCHQueriesLogic = kea<debugCHQueriesLogicType>([
    path(['lib', 'components', 'CommandPalette', 'DebugCHQueries']),
    actions({
        setPathFilter: (path: string | null) => ({ path }),
    }),
    reducers({
        pathFilter: [
            null as string | null,
            {
                setPathFilter: (_, { path }) => path,
            },
        ],
    }),
    loaders(({ props }: { props: { insightId: string } }) => ({
        debugResponse: [
            {} as DebugResponse,
            {
                loadDebugResponse: async () => {
                    const params = new URLSearchParams()
                    if (props.insightId) {
                        params.append('insight_id', props.insightId)
                    }
                    return await api.get(`api/debug_ch_queries/?${params.toString()}`)
                },
            },
        ],
    })),
    selectors({
        paths: [
            (s) => [s.debugResponse],
            (debugResponse: DebugResponse): [string, number][] | null => {
                return debugResponse.queries
                    ? Object.entries(
                          debugResponse.queries
                              .map((result) => result.path)
                              .reduce((acc: { [path: string]: number }, val: string) => {
                                  acc[val] = acc[val] === undefined ? 1 : (acc[val] += 1)
                                  return acc
                              }, {})
                      ).sort((a: any, b: any) => b[1] - a[1])
                    : null
            },
        ],
        filteredQueries: [
            (s) => [s.debugResponse, s.pathFilter],
            (debugReponse: DebugResponse, pathFilter: string | null) => {
                return pathFilter && debugReponse?.queries
                    ? debugReponse.queries.filter((item) => item.path === pathFilter)
                    : debugReponse.queries
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDebugResponse()
    }),
])

const generateHourlyLabels = (days: number): string[] => {
    const labels = []
    const now = dayjs().startOf('hour') // current hour
    for (let i = 0; i < days * 24; i++) {
        labels.push(now.subtract(i, 'hour').format('YYYY-MM-DDTHH:00:00'))
    }
    return labels.reverse()
}

const BarChartWithLine: React.FC<{ data: DataPoint[] }> = ({ data }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const labels = generateHourlyLabels(14)

    useEffect(() => {
        if (canvasRef.current) {
            Chart.register(ChartjsPluginStacked100, ChartDataLabels)

            const dataMap = new Map(data.map((d) => [d.hour, d]))

            const successfulQueries = labels.map((label) => dataMap.get(label)?.successful_queries || 0)
            const exceptions = labels.map((label) => dataMap.get(label)?.exceptions || 0)
            const avgResponseTime = labels.map((label) => dataMap.get(label)?.avg_response_time_ms || 0)

            const datasets: ChartDataset[] = [
                {
                    label: 'Successful Queries',
                    data: successfulQueries,
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 1,
                    stack: 'Stack 0',
                },
                {
                    label: 'Exceptions',
                    data: exceptions,
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    borderColor: 'rgba(255, 99, 132, 1)',
                    borderWidth: 1,
                    stack: 'Stack 0',
                },
                {
                    label: 'Avg Response Time (ms)',
                    data: avgResponseTime,
                    type: 'line',
                    fill: false,
                    borderColor: 'rgba(153, 102, 255, 0.5)',
                    yAxisID: 'y-axis-2',
                },
            ]

            const maxQueryCount = Math.max(...successfulQueries, ...exceptions)
            const maxResponseTime = Math.max(...avgResponseTime)
            const options: ChartConfiguration['options'] = {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        display: false,
                    },
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        max: maxQueryCount * 1.1,
                    },
                    'y-axis-2': {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        grid: {
                            drawOnChartArea: false,
                        },
                        max: maxResponseTime * 2, // Double to have more room for the other bars
                    },
                },
                plugins: {
                    datalabels: { display: false },
                },
            }

            const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'bar',
                data: { labels, datasets },
                options,
                plugins: [ChartDataLabels],
            })

            return () => newChart.destroy()
        }
    }, [data])

    return <canvas ref={canvasRef} className="h-[300px] w-full" />
}

interface DebugCHQueriesProps {
    insightId?: number | null
}

export function DebugCHQueries({ insightId }: DebugCHQueriesProps): JSX.Element {
    const logic = debugCHQueriesLogic({ insightId })
    const { debugResponseLoading, filteredQueries, pathFilter, paths, debugResponse } = useValues(logic)
    const { setPathFilter, loadDebugResponse } = useActions(logic)

    return (
        <>
            {!debugResponseLoading && !!debugResponse.hourly_stats ? (
                <div>
                    <BarChartWithLine data={debugResponse.hourly_stats} />
                </div>
            ) : null}
            <div className="flex gap-4 items-start justify-between mb-4">
                <div className="flex flex-wrap gap-2">
                    {!debugResponse.stats
                        ? paths?.map(([path, count]) => (
                              <LemonButton
                                  key={path}
                                  type={pathFilter === path ? 'primary' : 'tertiary'}
                                  size="small"
                                  onClick={() => (pathFilter === path ? setPathFilter(null) : setPathFilter(path))}
                              >
                                  {path} <span className="ml-0.5 text-muted ligatures-none">({count})</span>
                              </LemonButton>
                          ))
                        : null}
                    {!debugResponseLoading && !!debugResponse.stats ? (
                        <div className="flex flex-row space-x-4 p-4 border rounded bg-bg-light">
                            <div className="flex flex-col items-center">
                                <span className="text-sm font-bold">last 14 days</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-xl font-bold">{debugResponse.stats.total_queries}</span>
                                <span className="text-sm text-gray-600">Total queries</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-xl font-bold">{debugResponse.stats.total_exceptions}</span>
                                <span className="text-sm text-gray-600">Total exceptions</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-xl font-bold">
                                    {debugResponse.stats.average_query_duration_ms?.toFixed(2)} ms
                                </span>
                                <span className="text-sm text-gray-600">Avg query duration</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-xl font-bold">
                                    {debugResponse.stats.max_query_duration_ms} ms
                                </span>
                                <span className="text-sm text-gray-600">Max query duration</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-xl font-bold">
                                    {debugResponse.stats.exception_percentage?.toFixed(2)}%
                                </span>
                                <span className="text-sm text-gray-600">Exception %</span>
                            </div>
                        </div>
                    ) : null}
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    disabledReason={debugResponseLoading ? 'Loading…' : null}
                    onClick={() => loadDebugResponse()}
                    size="small"
                    type="secondary"
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonTable
                columns={[
                    {
                        title: 'Timestamp',
                        render: function Timestamp(_, item) {
                            return (
                                <>
                                    <div className="font-mono whitespace-pre mb-2">
                                        {dayjs.tz(item.timestamp, 'UTC').tz().format().replace('T', '\n')}
                                    </div>
                                    <div>
                                        {item.status === 1 ? (
                                            'In progress…'
                                        ) : (
                                            <>
                                                Took {Math.round((item.execution_time + Number.EPSILON) * 100) / 100} ms
                                            </>
                                        )}
                                    </div>
                                </>
                            )
                        },
                        width: 160,
                    },
                    {
                        title: 'Query',
                        render: function Query(_, item) {
                            return (
                                <div className="max-w-200 py-1 space-y-2">
                                    <div>
                                        <LemonTag className="inline-block">
                                            <span className="font-bold tracking-wide">ID:</span>{' '}
                                            <span className="font-mono">{item.query_id}</span>
                                        </LemonTag>{' '}
                                        {typeof item.logComment.cache_key === 'string' ? (
                                            <LemonTag className="inline-block">
                                                <span className="font-bold tracking-wide">Cache key:</span>{' '}
                                                <span className="font-mono">{item.logComment.cache_key}</span>{' '}
                                                <Link
                                                    to={`https://sentry.io/issues/?query=is%3Aunresolved+cache_key%3A${item.logComment.cache_key}&statsPeriod=7d`}
                                                    className="inline-block"
                                                    target="_blank"
                                                    targetBlankIcon
                                                />
                                            </LemonTag>
                                        ) : null}{' '}
                                        {typeof item.logComment.insight_id === 'number' ? (
                                            <LemonTag className="inline-block">
                                                <span className="font-bold tracking-wide">Insight ID:</span>{' '}
                                                <span className="font-mono">{item.logComment.insight_id}</span>{' '}
                                                <Link
                                                    to={`https://sentry.io/issues/?query=is%3Aunresolved+insight_id%3A${item.logComment.insight_id}&statsPeriod=7d`}
                                                    className="inline-block"
                                                    target="_blank"
                                                    targetBlankIcon
                                                />
                                            </LemonTag>
                                        ) : null}{' '}
                                        {typeof item.logComment.dashboard_id === 'number' ? (
                                            <LemonTag className="inline-block">
                                                <span className="font-bold tracking-wide">Dashboard ID:</span>{' '}
                                                <span className="font-mono">{item.logComment.dashboard_id}</span>{' '}
                                                <Link
                                                    to={`https://sentry.io/issues/?query=is%3Aunresolved+dashboard_id%3A${item.logComment.dashboard_id}&statsPeriod=7d`}
                                                    className="inline-block"
                                                    target="_blank"
                                                    targetBlankIcon
                                                />
                                            </LemonTag>
                                        ) : null}{' '}
                                        {typeof item.logComment.user_id === 'number' ? (
                                            <LemonTag className="inline-block">
                                                <span className="font-bold tracking-wide">User ID:</span>{' '}
                                                <span className="font-mono">{item.logComment.user_id}</span>{' '}
                                                <Link
                                                    to={`https://sentry.io/issues/?query=is%3Aunresolved+user%3A%22id%3A${item.logComment.user_id}%22&statsPeriod=7d`}
                                                    className="inline-block"
                                                    target="_blank"
                                                    targetBlankIcon
                                                />
                                            </LemonTag>
                                        ) : null}
                                    </div>
                                    {item.exception && (
                                        <LemonBanner type="error" className="text-xs font-mono">
                                            <div>{item.exception}</div>
                                            {typeof item.logComment.sentry_trace === 'string' ? (
                                                <LemonButton
                                                    type="secondary"
                                                    size="xsmall"
                                                    to={`https://sentry.io/issues/?query=is%3Aunresolved+trace%3A${
                                                        item.logComment.sentry_trace.split('-')[0]
                                                    }&statsPeriod=7d`}
                                                    targetBlank
                                                    className="mt-4 mb-1"
                                                >
                                                    View in Sentry
                                                </LemonButton>
                                            ) : null}
                                        </LemonBanner>
                                    )}
                                    <CodeSnippet
                                        language={Language.SQL}
                                        thing="query"
                                        maxLinesWithoutExpansion={10}
                                        className="text-sm max-w-[60vw]"
                                    >
                                        {item.query}
                                    </CodeSnippet>
                                    {typeof item.logComment.query === 'object' && item.logComment.query !== null ? (
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            fullWidth
                                            center
                                            icon={<IconCodeInsert />}
                                            to={urls.debugQuery(item.logComment.query)}
                                            targetBlank
                                            sideAction={{
                                                icon: <IconCopy />,
                                                onClick: () =>
                                                    void copyToClipboard(
                                                        JSON.stringify(item.logComment.query),
                                                        'query JSON'
                                                    ),
                                                tooltip: 'Copy query JSON to clipboard',
                                            }}
                                            className="my-0"
                                        >
                                            Debug{' '}
                                            {'kind' in item.logComment.query ? item.logComment.query.kind : 'query'} in
                                            new tab
                                        </LemonButton>
                                    ) : null}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Profiling stats',
                        render: function ProfilingStats(_, item) {
                            const [areAllStatsShown, setAreAllStatsShown] = useState(false)
                            const event = item['profile_events']
                            if (!event) {
                                return
                            }
                            return (
                                <div>
                                    {!areAllStatsShown ? (
                                        <table className="w-80">
                                            <tr>
                                                <td>Bytes selected (all nodes, uncompressed)</td>
                                                <td>
                                                    {event['SelectedBytes'] != null ? (
                                                        humanizeBytes(event['SelectedBytes'])
                                                    ) : (
                                                        <i>unknown</i>
                                                    )}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>Bytes read from disk (excl. page cache)</td>
                                                <td>
                                                    {event['OSReadBytes'] != null ? (
                                                        humanizeBytes(event['OSReadBytes'])
                                                    ) : (
                                                        <i>unknown</i>
                                                    )}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>Bytes read from disk (incl. page cache)</td>
                                                <td>
                                                    {event['OSReadChars'] != null ? (
                                                        humanizeBytes(event['OSReadChars'])
                                                    ) : (
                                                        <i>unknown</i>
                                                    )}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>Page cache hit rate</td>
                                                <td>
                                                    {event['OSReadBytes'] != null && event['OSReadChars'] != null ? (
                                                        `${Math.round(
                                                            ((event['OSReadChars'] - event['OSReadBytes']) /
                                                                event['OSReadChars']) *
                                                                100
                                                        )}%`
                                                    ) : (
                                                        <i>unknown</i>
                                                    )}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>Bytes received over network</td>
                                                <td>
                                                    {event['NetworkReceiveBytes'] != null ? (
                                                        humanizeBytes(event['NetworkReceiveBytes'])
                                                    ) : (
                                                        <i>unknown</i>
                                                    )}
                                                </td>
                                            </tr>
                                        </table>
                                    ) : (
                                        <CodeSnippet
                                            language={Language.JSON}
                                            maxLinesWithoutExpansion={0}
                                            key={item.query_id}
                                            className="text-sm mb-2"
                                        >
                                            {JSON.stringify(event, null, 2)}
                                        </CodeSnippet>
                                    )}
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        onClick={() => setAreAllStatsShown(!areAllStatsShown)}
                                        className="my-1"
                                        fullWidth
                                        center
                                    >
                                        {areAllStatsShown ? 'Show key stats only' : 'Show full raw stats'}
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
                dataSource={filteredQueries}
                loading={debugResponseLoading}
                loadingSkeletonRows={5}
                pagination={undefined}
                rowClassName="align-top"
            />
        </>
    )
}

import ChartDataLabels from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import { actions, afterMount, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCodeInsert, IconCopy, IconRefresh } from '@posthog/icons'

import { ChartConfiguration, ChartDataset } from 'lib/Chart'
import { Chart, ChartItem } from 'lib/Chart'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { humanizeBytes } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, Realm, Region } from '~/types'

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
                    // @ts-expect-error Types of library are out of date
                    crosshair: false,
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
    }, [data, labels])

    return <canvas ref={canvasRef} className="h-[300px] w-full" />
}

interface DebugCHQueriesProps {
    insightId?: number | null
}

export function DebugCHQueries({ insightId }: DebugCHQueriesProps): JSX.Element {
    const logic = debugCHQueriesLogic({ insightId })
    const { debugResponseLoading, filteredQueries, pathFilter, paths, debugResponse } = useValues(logic)
    const { setPathFilter, loadDebugResponse } = useActions(logic)

    const errorTrackingLink = (key: string, value: string | number): string => {
        return urls.errorTracking({
            filterGroup: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key,
                                value: [value],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
            },
        })
    }

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
                                  {path} <span className="ml-0.5 text-secondary ligatures-none">({count})</span>
                              </LemonButton>
                          ))
                        : null}
                    {!debugResponseLoading && !!debugResponse.stats ? (
                        <div className="flex flex-row deprecated-space-x-4 p-4 border rounded bg-surface-primary">
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
                                <div className="max-w-200 py-1 deprecated-space-y-2">
                                    <div>
                                        <LemonTag className="inline-block">
                                            <span className="font-bold tracking-wide">ID:</span>{' '}
                                            <span className="font-mono">{item.query_id}</span>
                                            <LinkMetabaseQuery queryId={item.query_id} />
                                        </LemonTag>{' '}
                                        {typeof item.logComment.cache_key === 'string' ? (
                                            <LemonTag className="inline-block">
                                                <span className="font-bold tracking-wide">Cache key:</span>{' '}
                                                <span className="font-mono">{item.logComment.cache_key}</span>{' '}
                                                <Link
                                                    to={errorTrackingLink('cache_key', item.logComment.cache_key)}
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
                                                    to={errorTrackingLink('insight_id', item.logComment.insight_id)}
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
                                                    to={errorTrackingLink('dashboard_id', item.logComment.dashboard_id)}
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
                                                    to={errorTrackingLink('user_id', item.logComment.user_id)}
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
                                            <span>
                                                {'kind' in item.logComment.query ? item.logComment.query.kind : 'query'}
                                            </span>{' '}
                                            in new tab
                                        </LemonButton>
                                    ) : null}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Metadata',
                        render: (_, item) => {
                            return (
                                <div className="space-y-4">
                                    <ProfilingStats item={item} />
                                    <QueryContext item={item} />
                                    <Timing item={item} />
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

function ProfilingStats({ item }: { item: Query }): JSX.Element | null {
    const [areAllStatsShown, setAreAllStatsShown] = useState(false)
    const event = item['profile_events']
    if (!event) {
        return null
    }
    return (
        <div>
            {!areAllStatsShown ? (
                <table className="w-80">
                    <tbody>
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
                                {event['OSReadBytes'] != null ? humanizeBytes(event['OSReadBytes']) : <i>unknown</i>}
                            </td>
                        </tr>
                        <tr>
                            <td>Bytes read from disk (incl. page cache)</td>
                            <td>
                                {event['OSReadChars'] != null ? humanizeBytes(event['OSReadChars']) : <i>unknown</i>}
                            </td>
                        </tr>
                        <tr>
                            <td>Page cache hit rate</td>
                            <td>
                                {event['OSReadBytes'] != null && event['OSReadChars'] != null ? (
                                    `${Math.round(
                                        ((event['OSReadChars'] - event['OSReadBytes']) / event['OSReadChars']) * 100
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
                    </tbody>
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
}

function QueryContext({ item }: { item: Query }): JSX.Element | null {
    const logComment = item.logComment

    const [showModifiers, setShowModifiers] = useState(false)

    if (!logComment) {
        return null
    }

    const { container_hostname, git_commit, modifiers, service_name, query } = logComment
    const { productKey, scene } = (query as any)?.tags || {}

    return (
        <div>
            <table className="w-80">
                <tbody>
                    {scene && typeof scene === 'string' ? (
                        <tr>
                            <td>Scene</td>
                            <td>{scene}</td>
                        </tr>
                    ) : null}
                    {productKey && typeof productKey === 'string' ? (
                        <tr>
                            <td>Product</td>
                            <td>{productKey}</td>
                        </tr>
                    ) : null}
                    {git_commit && typeof git_commit === 'string' ? (
                        <tr>
                            <td>Git commit SHA</td>
                            <td>
                                <LinkPosthogCommit commit={git_commit} />
                            </td>
                        </tr>
                    ) : null}
                    {service_name && typeof service_name === 'string' ? (
                        <tr>
                            <td>Service name</td>
                            <td>
                                <LinkPosthogService service={service_name} />
                            </td>
                        </tr>
                    ) : null}
                    <tr>
                        <td>Container hostname</td>
                        <td>{container_hostname}</td>
                    </tr>
                </tbody>
            </table>
            {modifiers && Object.keys(modifiers).length > 0 ? (
                showModifiers ? (
                    <CodeSnippet
                        language={Language.JSON}
                        maxLinesWithoutExpansion={0}
                        key={item.query_id}
                        className="text-sm mb-2 w-80"
                    >
                        {JSON.stringify(modifiers, null, 2)}
                    </CodeSnippet>
                ) : (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => setShowModifiers(!showModifiers)}
                        className="my-1"
                        fullWidth
                        center
                    >
                        {showModifiers ? 'Hide HogQLQueryModifiers' : 'Show HogQLQueryModifiers'}
                    </LemonButton>
                )
            ) : null}
        </div>
    )
}

function Timing({ item }: { item: Query }): JSX.Element | null {
    const timings = item.logComment?.timings as Record<string, number> | undefined

    const timingsSummary = useMemo(() => {
        if (!timings) {
            return null
        }
        const rootDuration = timings['.']

        let slowestSpan = { name: '', duration: 0 }
        const entries = Object.entries(timings)
        // Find the entries where the key is not a prefix of another key (with / as the separator).
        // This is quadratic, but the number of entries is small, do something smart if this becomes a problem
        const leafEntries = entries.filter(
            ([key]) => !entries.some(([otherKey]) => otherKey.startsWith(key + '/') && otherKey !== key)
        )
        for (const [key, val] of leafEntries) {
            if (val > slowestSpan.duration) {
                slowestSpan = { name: key, duration: val }
            }
        }
        return {
            rootDuration,
            slowestSpan: slowestSpan.name !== '' ? slowestSpan : null,
        }
    }, [timings])

    const [showFullTiming, setShowFullTiming] = useState(false)
    if (!timings || !timingsSummary) {
        return null
    }

    return (
        <div>
            {showFullTiming ? (
                <CodeSnippet
                    language={Language.JSON}
                    maxLinesWithoutExpansion={0}
                    key={item.query_id}
                    className="text-sm mb-2 w-80"
                >
                    {JSON.stringify(timings, null, 2)}
                </CodeSnippet>
            ) : (
                <table className="w-full">
                    <tbody>
                        <tr>
                            <td>Root span duration</td>
                            <td>{timingsSummary.rootDuration}</td>
                        </tr>
                        {timingsSummary.slowestSpan ? (
                            <>
                                <tr>
                                    <td>Slowest span</td>
                                    <td>
                                        <div
                                            className="w-60 overflow-auto"
                                            ref={(element) => element?.scrollTo({ left: element?.scrollWidth })}
                                        >
                                            {timingsSummary.slowestSpan.name}
                                        </div>
                                    </td>
                                </tr>
                                <tr>
                                    <td>Slowest span duration</td>
                                    <td>{timingsSummary.slowestSpan.duration}</td>
                                </tr>
                            </>
                        ) : null}
                    </tbody>
                </table>
            )}
            <LemonButton
                type="secondary"
                size="xsmall"
                onClick={() => setShowFullTiming(!showFullTiming)}
                className="my-1"
                fullWidth
                center
            >
                {showFullTiming ? 'Show slowest span only' : 'Show full timing'}
            </LemonButton>
        </div>
    )
}

function LinkPosthogCommit({ commit }: { commit: string }): JSX.Element {
    return (
        <Link to={`https://www.github.com/PostHog/posthog/commit/${commit}`} target="_blank">
            {commit}
        </Link>
    )
}

function LinkPosthogService({ service }: { service: string }): JSX.Element {
    if (service.includes('local-dev')) {
        return <span>{service}</span>
    }

    return (
        <Link
            to={`https://argocd-internal.internal.posthog.dev/applications?search=${encodeURIComponent(service)}`}
            target="_blank"
        >
            {service}
        </Link>
    )
}

function LinkMetabaseQuery({ queryId }: { queryId: string }): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const region = preflight?.region
    const realm = preflight?.realm

    if (realm !== Realm.Cloud || !(region === Region.US || region === Region.EU)) {
        return null
    }

    const url =
        region === Region.US
            ? `https://metabase.prod-us.posthog.dev/question?query_id=${queryId}#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiIgICAgc2VsZWN0IFxuICAgICAgICBxdWVyeV9pZCxcbiAgICAgICAgdXNlcixcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdxdWVyeScsICd0YWdzJywgJ3Byb2R1Y3RLZXknKSBhcyBwcm9kdWN0S2V5LFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3F1ZXJ5JywgJ3RhZ3MnLCAnc2NlbmUnKSBhcyBzY2VuZSxcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdxdWVyeScsICd0YWdzJykgYXMgYWxsX3RhZ3MsXG4gICAgICAgIEpTT05FeHRyYWN0U3RyaW5nKGxvZ19jb21tZW50LCAnaWQnKSBhcyBpZCxcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdxdWVyeV90eXBlJykgYXMgcXVlcnlfdHlwZSxcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdxdWVyeScsICdraW5kJykgYXMgcV9raW5kLFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3JvdXRlX2lkJykgYXMgcm91dGVfaWQsXG4gICAgICAgIEpTT05FeHRyYWN0U3RyaW5nKGxvZ19jb21tZW50LCAnc2VydmljZV9uYW1lJykgYXMgc2VydmljZV9uYW1lLFxuICAgICAgICByZWFkX2J5dGVzLFxuICAgICAgICBxdWVyeV9kdXJhdGlvbl9tcyxcbiAgICAgICAgUHJvZmlsZUV2ZW50c1snUmVhbFRpbWVNaWNyb3NlY29uZHMnXS8xMDAwMDAwIGFzIFJlYWxUaW1lLFxuICAgICAgICBQcm9maWxlRXZlbnRzWydPU0NQVVZpcnR1YWxUaW1lTWljcm9zZWNvbmRzJ10vMTAwMDAwMCBhcyBPU0NQVVZpcnR1YWxUaW1lLFxuICAgICAgICBxdWVyeSxcbiAgICAgICAgbG9nX2NvbW1lbnQsXG4gICAgICAgIHF1ZXJ5X2R1cmF0aW9uX21zIC8gMTAwMCBhcyBxdWVyeV9kdXJhdGlvbl9zZWMsXG4gICAgICAgIG1lbW9yeV91c2FnZSxcbiAgICAgICAgcGVha190aHJlYWRzX3VzYWdlLFxuICAgIGZyb20gY2x1c3RlckFsbFJlcGxpY2FzKHBvc3Rob2csIHN5c3RlbS5xdWVyeV9sb2cpXG4gICAgd2hlcmUgXG4gICAgICAgIGFuZChcbiAgICAgICAgICAgIHRydWVcbiAgICAgICAgICAgICwgZXZlbnRfZGF0ZSA-PSB0b2RheSgpIC0gN1xuICAgICAgICAgICAgLCBpc19pbml0aWFsX3F1ZXJ5XG4gICAgICAgICAgICAsIHR5cGUgIT0gJ1F1ZXJ5U3RhcnQnXG4gICAgICAgICAgICAsIHVzZXIgPSAnYXBwJ1xuICAgICAgICAgICAgLCBxdWVyeV9pZCA9IHt7cXVlcnlfaWR9fVxuICAgICAgICApXG4gICAgb3JkZXIgYnkgZXZlbnRfdGltZSBkZXNjXG4gICAgbGltaXQgMTAwIiwidGVtcGxhdGUtdGFncyI6eyJxdWVyeV9pZCI6eyJ0eXBlIjoidGV4dCIsIm5hbWUiOiJxdWVyeV9pZCIsImlkIjoiNDA5MWQ1YTctMzFhMy00YjFkLTlmODctZDk5MGJlNDI1ODg0IiwiZGlzcGxheS1uYW1lIjoiUXVlcnkgSUQifX19LCJkYXRhYmFzZSI6NDJ9LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbeyJpZCI6IjQwOTFkNWE3LTMxYTMtNGIxZC05Zjg3LWQ5OTBiZTQyNTg4NCIsInR5cGUiOiJjYXRlZ29yeSIsInRhcmdldCI6WyJ2YXJpYWJsZSIsWyJ0ZW1wbGF0ZS10YWciLCJxdWVyeV9pZCJdXSwibmFtZSI6IlF1ZXJ5IElEIiwic2x1ZyI6InF1ZXJ5X2lkIn1dLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=`
            : `https://metabase.prod-eu.posthog.dev/question?query_id=${queryId}#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJkYXRhYmFzZSI6NDIsIm5hdGl2ZSI6eyJxdWVyeSI6IiAgICBzZWxlY3QgXG4gICAgICAgIHF1ZXJ5X2lkLFxuICAgICAgICB1c2VyLFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3F1ZXJ5JywgJ3RhZ3MnLCAncHJvZHVjdEtleScpIGFzIHByb2R1Y3RLZXksXG4gICAgICAgIEpTT05FeHRyYWN0U3RyaW5nKGxvZ19jb21tZW50LCAncXVlcnknLCAndGFncycsICdzY2VuZScpIGFzIHNjZW5lLFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3F1ZXJ5JywgJ3RhZ3MnKSBhcyBhbGxfdGFncyxcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdpZCcpIGFzIGlkLFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3F1ZXJ5X3R5cGUnKSBhcyBxdWVyeV90eXBlLFxuICAgICAgICBKU09ORXh0cmFjdFN0cmluZyhsb2dfY29tbWVudCwgJ3F1ZXJ5JywgJ2tpbmQnKSBhcyBxX2tpbmQsXG4gICAgICAgIEpTT05FeHRyYWN0U3RyaW5nKGxvZ19jb21tZW50LCAncm91dGVfaWQnKSBhcyByb3V0ZV9pZCxcbiAgICAgICAgSlNPTkV4dHJhY3RTdHJpbmcobG9nX2NvbW1lbnQsICdzZXJ2aWNlX25hbWUnKSBhcyBzZXJ2aWNlX25hbWUsXG4gICAgICAgIHJlYWRfYnl0ZXMsXG4gICAgICAgIHF1ZXJ5X2R1cmF0aW9uX21zLFxuICAgICAgICBQcm9maWxlRXZlbnRzWydSZWFsVGltZU1pY3Jvc2Vjb25kcyddLzEwMDAwMDAgYXMgUmVhbFRpbWUsXG4gICAgICAgIFByb2ZpbGVFdmVudHNbJ09TQ1BVVmlydHVhbFRpbWVNaWNyb3NlY29uZHMnXS8xMDAwMDAwIGFzIE9TQ1BVVmlydHVhbFRpbWUsXG4gICAgICAgIHF1ZXJ5LFxuICAgICAgICBsb2dfY29tbWVudCxcbiAgICAgICAgcXVlcnlfZHVyYXRpb25fbXMgLyAxMDAwIGFzIHF1ZXJ5X2R1cmF0aW9uX3NlYyxcbiAgICAgICAgbWVtb3J5X3VzYWdlLFxuICAgICAgICBwZWFrX3RocmVhZHNfdXNhZ2UsXG4gICAgZnJvbSBjbHVzdGVyQWxsUmVwbGljYXMocG9zdGhvZywgc3lzdGVtLnF1ZXJ5X2xvZylcbiAgICB3aGVyZSBcbiAgICAgICAgYW5kKFxuICAgICAgICAgICAgdHJ1ZVxuICAgICAgICAgICAgLCBldmVudF9kYXRlID49IHRvZGF5KCkgLSA3XG4gICAgICAgICAgICAsIGlzX2luaXRpYWxfcXVlcnlcbiAgICAgICAgICAgICwgdHlwZSAhPSAnUXVlcnlTdGFydCdcbiAgICAgICAgICAgICwgdXNlciA9ICdhcHAnXG4gICAgICAgICAgICAsIHF1ZXJ5X2lkID0ge3txdWVyeV9pZH19XG4gICAgICAgIClcbiAgICBvcmRlciBieSBldmVudF90aW1lIGRlc2NcbiAgICBsaW1pdCAxMDAiLCJ0ZW1wbGF0ZS10YWdzIjp7InF1ZXJ5X2lkIjp7InR5cGUiOiJ0ZXh0IiwibmFtZSI6InF1ZXJ5X2lkIiwiaWQiOiI0MDkxZDVhNy0zMWEzLTRiMWQtOWY4Ny1kOTkwYmU0MjU4ODQiLCJkaXNwbGF5LW5hbWUiOiJRdWVyeSBJRCJ9fX19LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbeyJpZCI6IjQwOTFkNWE3LTMxYTMtNGIxZC05Zjg3LWQ5OTBiZTQyNTg4NCIsInR5cGUiOiJjYXRlZ29yeSIsInRhcmdldCI6WyJ2YXJpYWJsZSIsWyJ0ZW1wbGF0ZS10YWciLCJxdWVyeV9pZCJdXSwibmFtZSI6IlF1ZXJ5IElEIiwic2x1ZyI6InF1ZXJ5X2lkIn1dLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=`
    return <Link to={url} className="inline-block" target="_blank" targetBlankIcon />
}

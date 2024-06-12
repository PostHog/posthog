import { IconCodeInsert, IconCopy } from '@posthog/icons'
import { actions, afterMount, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { humanizeBytes } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useState } from 'react'
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

export interface Query {
    /** @example '2023-07-27T10:06:11' */
    timestamp: string
    query: string
    query_id: string
    queryJson: string
    exception: string
    /**
     * 1 means running, 2 means finished, 3 means errored before execution, 4 means errored during execution.
     *
     * @see `type` column in https://clickhouse.com/docs/en/operations/system-tables/query_log */
    status: 1 | 2 | 3 | 4
    execution_time: number
    path: string
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
    loaders({
        queries: [
            [] as Query[],
            {
                loadQueries: async () => {
                    return await api.get('api/debug_ch_queries/')
                },
            },
        ],
    }),
    selectors({
        paths: [
            (s) => [s.queries],
            (queries: Query[]): [string, number][] | null => {
                return queries
                    ? Object.entries(
                          queries
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
            (s) => [s.queries, s.pathFilter],
            (queries: Query[], pathFilter: string | null) => {
                return pathFilter && queries ? queries.filter((item) => item.path === pathFilter) : queries
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadQueries()
    }),
])

function DebugCHQueries(): JSX.Element {
    const { queriesLoading, filteredQueries, pathFilter, paths } = useValues(debugCHQueriesLogic)
    const { setPathFilter, loadQueries } = useActions(debugCHQueriesLogic)

    return (
        <>
            <div className="flex gap-4 items-end justify-between mb-4">
                <div className="flex flex-wrap gap-2">
                    {paths?.map(([path, count]) => (
                        <LemonButton
                            key={path}
                            type={pathFilter === path ? 'primary' : 'tertiary'}
                            size="small"
                            onClick={() => (pathFilter === path ? setPathFilter(null) : setPathFilter(path))}
                        >
                            {path} <span className="ml-0.5 text-muted ligatures-none">({count})</span>
                        </LemonButton>
                    ))}
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    disabledReason={queriesLoading ? 'Loading…' : null}
                    onClick={() => loadQueries()}
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
                                <span className="font-mono whitespace-pre">
                                    {dayjs.tz(item.timestamp, 'UTC').tz().format().replace('T', '\n')}
                                </span>
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
                                        <span className="font-bold tracking-wide">ID:</span>{' '}
                                        <span className="font-mono">{item.query_id}</span>
                                    </div>
                                    {item.exception && (
                                        <LemonBanner type="error" className="text-xs font-mono">
                                            {item.exception}
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
                                    {item.queryJson ? (
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            fullWidth
                                            center
                                            icon={<IconCodeInsert />}
                                            to={urls.debugQuery(item.queryJson)}
                                            targetBlank
                                            sideAction={{
                                                icon: <IconCopy />,
                                                onClick: () => void copyToClipboard(item.queryJson, 'query JSON'),
                                                tooltip: 'Copy query JSON to clipboard',
                                            }}
                                            className="my-0"
                                        >
                                            Debug {JSON.parse(item.queryJson).kind || 'query'} in new tab
                                        </LemonButton>
                                    ) : null}
                                </div>
                            )
                        },
                    },

                    {
                        title: 'Duration',
                        render: function Duration(_, item) {
                            if (item.status === 1) {
                                return 'In progress…'
                            }
                            return <>{Math.round((item.execution_time + Number.EPSILON) * 100) / 100} ms</>
                        },
                        align: 'right',
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
                                                        `${
                                                            ((event['OSReadChars'] - event['OSReadBytes']) /
                                                                event['OSReadChars']) *
                                                            100
                                                        }%`
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
                loading={queriesLoading}
                loadingSkeletonRows={5}
                pagination={undefined}
            />
        </>
    )
}

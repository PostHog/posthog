import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { CodeSnippet, Language } from '../CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { actions, afterMount, kea, reducers, selectors, useActions, useValues, path } from 'kea'
import { loaders } from 'kea-loaders'
import type { debugCHQueriesLogicType } from './DebugCHQueriesType'
import { IconRefresh } from 'lib/lemon-ui/icons'

export function openCHQueriesDebugModal(): void {
    LemonDialog.open({
        title: 'ClickHouse queries recently executed for this user',
        content: <DebugCHQueries />,
        primaryButton: null,
        width: 1200,
    })
}

export interface Query {
    /** @example '2023-07-27T10:06:11' */
    timestamp: string
    query: string
    exception: string
    type: number
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
            {!!paths?.length && (
                <div className="flex gap-4 items-end justify-between mb-4">
                    <div className="flex flex-wrap gap-2">
                        {paths.map(([path, count]) => (
                            <LemonButton
                                key={path}
                                type={pathFilter === path ? 'primary' : 'tertiary'}
                                size="small"
                                onClick={() => (pathFilter === path ? setPathFilter(null) : setPathFilter(path))}
                            >
                                {path} ({count})
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
            )}

            <LemonTable
                columns={[
                    {
                        title: 'Timestamp',
                        render: (_, item) => (
                            <span className="font-mono whitespace-pre">
                                {dayjs.tz(item.timestamp, 'UTC').tz().format().replace('T', '\n')}
                            </span>
                        ),
                        width: 160,
                    },
                    {
                        title: 'Query',
                        render: function query(_, item) {
                            return (
                                <div className="max-w-200">
                                    {item.exception && (
                                        <LemonBanner type="error" className="text-xs font-mono">
                                            {item.exception}
                                        </LemonBanner>
                                    )}
                                    <CodeSnippet
                                        language={Language.SQL}
                                        thing="query"
                                        maxLinesWithoutExpansion={5}
                                        style={{ fontSize: 12 }}
                                    >
                                        {item.query}
                                    </CodeSnippet>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Duration',
                        render: function exec(_, item) {
                            return <>{Math.round((item.execution_time + Number.EPSILON) * 100) / 100} ms</>
                        },
                        align: 'right',
                    },
                ]}
                dataSource={filteredQueries}
                loading={queriesLoading}
                loadingSkeletonRows={5}
                size="small"
                pagination={undefined}
            />
        </>
    )
}

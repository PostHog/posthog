import { IconRewindPlay } from '@posthog/icons'
import { LemonInput, LemonTable, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { useState } from 'react'
import { EventDetails } from 'scenes/events/EventDetails'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { logsSceneLogic } from 'scenes/logs/logsSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { useDebouncedCallback } from 'use-debounce'

import { AutoLoad } from '~/queries/nodes/DataNode/AutoLoad'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { LoadNext } from '~/queries/nodes/DataNode/LoadNext'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { PropertyGroupFilters } from '~/queries/nodes/InsightViz/PropertyGroupFilters/PropertyGroupFilters'
import { Query } from '~/queries/Query/Query'
import { LogsQuery, NodeKind } from '~/queries/schema'

import { logsDataLogic } from './logsDataLogic'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
}

export function LogsScene(): JSX.Element {
    const { query } = useValues(logsSceneLogic)

    const props = {
        key: 'logs',
        query,
    }

    return (
        <BindLogic logic={logsDataLogic} props={props}>
            <BindLogic logic={dataNodeLogic} props={props}>
                <SomeComponent />
            </BindLogic>
        </BindLogic>
    )
}

const SomeComponent = (): JSX.Element => {
    const [localSearchTerm, setLocalSearchTerm] = useState('')
    const { data, responseLoading, query } = useValues(logsDataLogic)
    const { setQuery } = useActions(logsSceneLogic)

    const setSearchTerm = useDebouncedCallback((value: string) => setQuery({ searchTerm: value }), 500)

    return (
        <div className="relative w-full flex flex-col gap-4 flex-1 h-full">
            <div className="flex gap-4 justify-between flex-wrap">
                <div className="flex grow gap-4 items-center">
                    <DateRange key="date-range" query={query as LogsQuery} setQuery={setQuery} />
                    <LemonInput
                        placeholder="Search..."
                        onChange={(value) => {
                            // Local useState is required for `allowClear` to work
                            setLocalSearchTerm(value)
                            setSearchTerm(value)
                        }}
                        value={localSearchTerm}
                        allowClear
                        className="w-full"
                    />
                </div>
            </div>

            <div className="flex gap-4 justify-between flex-wrap">
                <div className="flex grow gap-4 items-center">
                    <Filters />
                </div>
            </div>

            <div className="flex gap-4 justify-between flex-wrap">
                <div className="flex gap-4 items-center">
                    <Reload />
                    <AutoLoad />
                </div>
            </div>

            <div className="py-2 max-h-60 overflow-hidden">
                <h2>Log volume</h2>
                <Query
                    key="logs"
                    readOnly={true}
                    query={{
                        kind: NodeKind.InsightVizNode,
                        full: false,
                        embedded: true,
                        fitParentHeight: true,
                        source: {
                            ...query,
                            kind: NodeKind.TrendsQuery,
                            filterTestAccounts: false,
                            breakdownFilter: {
                                breakdown_type: 'hogql',
                                breakdown: 'upper(properties.$level)',
                            },
                            series: [
                                {
                                    kind: 'EventsNode',
                                    event: '$log',
                                    name: '$log',
                                    math: 'total',
                                },
                            ],
                            interval: 'day',
                            trendsFilter: {
                                display: 'ActionsBar',
                            },
                        },
                    }}
                />
            </div>

            <LemonTable
                dataSource={data}
                loading={responseLoading}
                columns={[
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        render: (_, log) => {
                            return <TZLabel time={log.timestamp} showSeconds />
                        },
                    },
                    {
                        title: 'Level',
                        key: 'level',
                        width: 80,
                        render: (_, log) => {
                            const logLevels: Record<string, LemonTagType> = {
                                WARNING: 'warning',
                                VERBOSE: 'success',
                                INFO: 'success',
                                DEBUG: 'success',
                                ERROR: 'danger',
                            }
                            return (
                                <LemonTag type={logLevels[log.level.toUpperCase()] ?? 'default'}>
                                    {log.level.toUpperCase()}
                                </LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Message',
                        key: 'msg',
                        render: (_, log) => {
                            const namespace = log.namespace ? (
                                <span className="text-[color:var(--purple)]">[{log.namespace}] </span>
                            ) : null

                            return (
                                <>
                                    {namespace}
                                    {log.msg}
                                </>
                            )
                        },
                    },
                    {
                        title: '',
                        width: 0,
                        key: 'recording',
                        render: (_, log) => {
                            if (!log.session_id) {
                                return null
                            }

                            return (
                                <Link to={urls.replaySingle(log.session_id)} target="_new">
                                    <IconRewindPlay />
                                </Link>
                            )
                        },
                    },
                ]}
                expandable={{
                    collapseOnLoading: true,
                    expandedRowRender: (log) => {
                        return (
                            <EventDetails
                                event={{
                                    id: log.uuid,
                                    distinct_id: log.distinct_id,
                                    event: log.event,
                                    elements: [],
                                    timestamp: log.timestamp,
                                    properties: JSON.parse(log.properties),
                                }}
                            />
                        )
                    },
                }}
                footer={<LoadNext query={query} />}
            />
        </div>
    )
}

const Filters = (): JSX.Element => {
    const { setQuery } = useActions(logsSceneLogic)
    const { query } = useValues(logsDataLogic)

    return (
        <PropertyGroupFilters
            insightProps={{ dashboardItemId: 'new', setQuery: ((query: LogsQuery) => setQuery(query)) as any }} // Forcing some prop typings
            pageKey={`${keyForInsightLogicProps('new')({
                dashboardItemId: 'new',
                setQuery: ((query: LogsQuery) => setQuery(query)) as any, // Forcing some prop typings
            })}-Logs`}
            query={query as LogsQuery}
            setQuery={((query: LogsQuery) => setQuery(query)) as any} // Forcing some prop typings
            eventNames={['$log']}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            isDataWarehouseSeries={false}
        />
    )
}

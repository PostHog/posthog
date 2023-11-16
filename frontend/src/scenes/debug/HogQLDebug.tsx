import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { DataNode, HogQLQuery, HogQLQueryResponse } from '~/queries/schema'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { BindLogic, useValues } from 'kea'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime, Timings } from '~/queries/nodes/DataNode/ElapsedTime'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { CodeEditor } from 'lib/components/CodeEditors'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Reload } from '~/queries/nodes/DataNode/Reload'

interface HogQLDebugProps {
    queryKey: string
    query: HogQLQuery
    setQuery: (query: DataNode) => void
}
export function HogQLDebug({ query, setQuery, queryKey }: HogQLDebugProps): JSX.Element {
    const dataNodeLogicProps: DataNodeLogicProps = { query, key: queryKey }
    const { dataLoading, response, responseErrorObject, elapsedTime } = useValues(dataNodeLogic(dataNodeLogicProps))
    const clickHouseTime = (response as HogQLQueryResponse)?.timings?.find(({ k }) => k === './clickhouse_execute')?.t

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div className="space-y-2">
                <HogQLQueryEditor query={query} setQuery={setQuery} />
                <div className="flex gap-2">
                    <Reload />
                    <DateRange key="date-range" query={query} setQuery={setQuery} />
                    <EventPropertyFilters key="event-property" query={query} setQuery={setQuery} />
                </div>
                <div className="flex gap-2">
                    <LemonLabel>
                        POE:
                        <LemonSelect
                            options={[
                                { value: 'disabled', label: 'Disabled' },
                                { value: 'v1_enabled', label: 'V1 Enabled' },
                                { value: 'v1_mixed', label: 'V1 Mixed' },
                                { value: 'v2_enabled', label: 'V2 Enabled' },
                            ]}
                            onChange={(value) =>
                                setQuery({
                                    ...query,
                                    modifiers: { ...query.modifiers, personsOnEventsMode: value },
                                } as HogQLQuery)
                            }
                            value={query.modifiers?.personsOnEventsMode ?? response?.modifiers?.personsOnEventsMode}
                        />
                    </LemonLabel>
                    <LemonLabel>
                        Persons ArgMax:
                        <LemonSelect
                            options={[
                                { value: 'v1', label: 'V1' },
                                { value: 'v2', label: 'V2' },
                            ]}
                            onChange={(value) =>
                                setQuery({
                                    ...query,
                                    modifiers: { ...query.modifiers, personsArgMaxVersion: value },
                                } as HogQLQuery)
                            }
                            value={query.modifiers?.personsArgMaxVersion ?? response?.modifiers?.personsArgMaxVersion}
                        />
                    </LemonLabel>
                    <LemonLabel>
                        In Cohort Via:
                        <LemonSelect
                            options={[
                                { value: 'join', label: 'join' },
                                { value: 'subquery', label: 'subquery' },
                            ]}
                            onChange={(value) =>
                                setQuery({
                                    ...query,
                                    modifiers: { ...query.modifiers, inCohortVia: value },
                                } as HogQLQuery)
                            }
                            value={query.modifiers?.inCohortVia ?? response?.modifiers?.inCohortVia}
                        />
                    </LemonLabel>
                    <LemonLabel>
                        Materialization Mode:
                        <LemonSelect
                            options={[
                                { value: 'auto', label: 'auto' },
                                { value: 'legacy_null_as_string', label: 'legacy_null_as_string' },
                                { value: 'legacy_null_as_null', label: 'legacy_null_as_null' },
                                { value: 'disabled', label: 'disabled' },
                            ]}
                            onChange={(value) =>
                                setQuery({
                                    ...query,
                                    modifiers: { ...query.modifiers, materializationMode: value },
                                } as HogQLQuery)
                            }
                            value={query.modifiers?.materializationMode ?? response?.modifiers?.materializationMode}
                        />
                    </LemonLabel>
                </div>
                {dataLoading ? (
                    <>
                        <h2>Running query...</h2>
                        <div className="flex">
                            Time elapsed: <ElapsedTime />
                        </div>
                    </>
                ) : (
                    <>
                        {response?.error ? (
                            <>
                                <h2 className="text-danger">Error Running Query!</h2>
                                <CodeSnippet language={Language.Text} wrap>
                                    {response.error}
                                </CodeSnippet>
                            </>
                        ) : null}
                        {response?.hogql ? (
                            <>
                                <h2>Executed HogQL</h2>
                                <CodeSnippet language={Language.SQL} wrap>
                                    {response.hogql}
                                </CodeSnippet>
                            </>
                        ) : null}
                        {response?.clickhouse ? (
                            <>
                                <h2>
                                    Executed ClickHouse SQL
                                    {clickHouseTime !== undefined
                                        ? ` (${Math.floor(clickHouseTime * 1000) / 1000}s)`
                                        : ''}
                                </h2>
                                <CodeSnippet language={Language.SQL} wrap>
                                    {response.clickhouse}
                                </CodeSnippet>
                            </>
                        ) : null}
                        {response?.explain ? (
                            <>
                                <h2>Explained ClickHouseSQL</h2>
                                <CodeSnippet wrap>{response.explain.join('\n')}</CodeSnippet>
                            </>
                        ) : null}
                        {response?.timings && elapsedTime !== null ? (
                            <>
                                <h2>Time spent</h2>
                                <Timings timings={response.timings} elapsedTime={elapsedTime} />
                            </>
                        ) : null}
                        <h2>Raw response</h2>
                        <CodeEditor
                            className="border"
                            language={'json'}
                            value={JSON.stringify(response ?? responseErrorObject, null, 2)}
                            height={800}
                        />
                    </>
                )}
            </div>
        </BindLogic>
    )
}

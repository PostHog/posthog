import { BindLogic, useValues } from 'kea'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Modifiers } from 'scenes/debug/Modifiers'

import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { HogQLQuery, HogQLQueryModifiers, HogQLQueryResponse } from '~/queries/schema/schema-general'

import { QueryTabs } from './QueryTabs'

interface HogQLDebugProps {
    queryKey: `new-${string}`
    query: HogQLQuery
    setQuery: (query: HogQLQuery) => void
    modifiers?: HogQLQueryModifiers
}

export function HogQLDebug({ query, setQuery, queryKey, modifiers }: HogQLDebugProps): JSX.Element {
    const dataNodeLogicProps: DataNodeLogicProps = {
        query,
        key: queryKey,
        dataNodeCollectionId: queryKey,
        modifiers,
    }
    const { dataLoading, response: _response } = useValues(dataNodeLogic(dataNodeLogicProps))
    const response = _response as HogQLQueryResponse | null

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div className="deprecated-space-y-2">
                <HogQLQueryEditor query={query} setQuery={setQuery} />
                <Modifiers setQuery={setQuery} query={query} response={response} />
                <LemonDivider className="my-4" />
                <div className="flex flex-wrap gap-2 ">
                    <Reload />
                    <DateRange key="date-range" query={query} setQuery={setQuery} />
                    <EventPropertyFilters key="event-property" query={query} setQuery={setQuery} />
                </div>
                {dataLoading ? (
                    <>
                        <h2>Running query...</h2>
                        <div className="flex">
                            Time elapsed:&nbsp;
                            <ElapsedTime />
                        </div>
                    </>
                ) : (
                    <>
                        <QueryTabs
                            query={query}
                            response={response}
                            setQuery={setQuery}
                            queryKey={queryKey}
                            onLoadQuery={(queryString) => {
                                try {
                                    const parsed = JSON.parse(queryString)
                                    if (parsed.kind === 'HogQLQuery') {
                                        setQuery(parsed)
                                    }
                                } catch (e) {
                                    console.error('Failed to parse query from log', e)
                                }
                            }}
                        />
                    </>
                )}
            </div>
        </BindLogic>
    )
}

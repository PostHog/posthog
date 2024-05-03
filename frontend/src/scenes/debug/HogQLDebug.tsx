import { BindLogic, useValues } from 'kea'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Modifiers } from 'scenes/debug/Modifiers'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { HogQLQuery, HogQLQueryResponse } from '~/queries/schema'

import { QueryTabs } from './QueryTabs'

interface HogQLDebugProps {
    queryKey: `new-${string}`
    query: HogQLQuery
    setQuery: (query: HogQLQuery) => void
}

export function HogQLDebug({ query, setQuery, queryKey }: HogQLDebugProps): JSX.Element {
    const dataNodeLogicProps: DataNodeLogicProps = { query, key: queryKey, dataNodeCollectionId: queryKey }
    const { dataLoading, response: _response } = useValues(dataNodeLogic(dataNodeLogicProps))
    const response = _response as HogQLQueryResponse | null

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div className="space-y-2">
                <HogQLQueryEditor query={query} setQuery={setQuery} />
                <Modifiers setQuery={setQuery} query={query} response={response} />
                <LemonDivider className="my-4" />
                <div className="flex gap-2">
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
                        <QueryTabs query={query} response={response} setQuery={setQuery} queryKey={queryKey} />
                    </>
                )}
            </div>
        </BindLogic>
    )
}

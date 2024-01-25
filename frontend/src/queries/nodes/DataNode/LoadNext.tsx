import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema'
import { isActorsQuery, isHogQLQuery, isPersonsNode } from '~/queries/utils'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { canLoadNextData, nextDataLoading, numberOfRows, hasMoreData, dataLimit } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    return (
        <div className="m-2 flex items-center">
            <LemonButton onClick={loadNextData} loading={nextDataLoading} fullWidth center disabled={!canLoadNextData}>
                {isHogQLQuery(query) && !canLoadNextData && hasMoreData && dataLimit ? (
                    <>
                        <br />
                        Default limit of {dataLimit} rows reached. Try adding a LIMIT clause to adjust.
                    </>
                ) : (
                    <>
                        Showing {canLoadNextData || numberOfRows === 1 ? '' : 'all '}
                        {numberOfRows === 1 ? 'one' : numberOfRows}{' '}
                        {isPersonsNode(query) || isActorsQuery(query)
                            ? numberOfRows === 1
                                ? 'person'
                                : 'people'
                            : numberOfRows === 1
                            ? 'event'
                            : 'events'}
                        {canLoadNextData ? '. Click to load more.' : '. Reached the end of results.'}
                    </>
                )}
            </LemonButton>
        </div>
    )
}

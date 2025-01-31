import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema'
import { isHogQLQuery } from '~/queries/utils'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { canLoadNextData, nextDataLoading, numberOfRows, hasMoreData, dataLimit } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    // No data means the user is controlling the pagination
    if (!dataLimit) {
        return <></>
    }

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
                        Showing{' '}
                        {hasMoreData && (numberOfRows ?? 0) > 1
                            ? 'first '
                            : canLoadNextData || numberOfRows === 1
                            ? ''
                            : 'all '}
                        {numberOfRows === 1 ? 'one' : numberOfRows} {numberOfRows === 1 ? 'entry' : 'entries'}
                        {canLoadNextData ? '. Click to load more.' : hasMoreData ? '' : '. Reached the end of results.'}
                    </>
                )}
            </LemonButton>
        </div>
    )
}

export function LoadPreviewText(): JSX.Element {
    const { numberOfRows, hasMoreData } = useValues(dataNodeLogic)

    if (!hasMoreData) {
        return <></>
    }

    return (
        <>
            Showing {hasMoreData && (numberOfRows ?? 0) > 1 ? 'first ' : ' '}
            {numberOfRows === 1 ? 'one' : numberOfRows} {numberOfRows === 1 ? 'entry' : 'entries'}
        </>
    )
}

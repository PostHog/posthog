import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useMemo } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema/schema-general'

interface LoadNextProps {
    query: DataNode
}

export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { canLoadNextData, nextDataLoading, numberOfRows, hasMoreData, dataLimit } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    const text = useMemo(() => {
        let result = `Showing ${
            hasMoreData && (numberOfRows ?? 0) > 1 ? 'first ' : canLoadNextData || numberOfRows === 1 ? '' : 'all '
        }${numberOfRows === 1 ? 'one' : numberOfRows} ${numberOfRows === 1 ? 'entry' : 'entries'}`
        if (canLoadNextData) {
            result += nextDataLoading ? ' – loading more…' : ' – click to load more'
        } else if (hasMoreData) {
            result += ' – reached the end of results'
        }
        return result
    }, [query, dataLimit, numberOfRows, canLoadNextData, nextDataLoading, hasMoreData])

    return (
        <div className="m-2 flex items-center">
            <LemonButton onClick={loadNextData} loading={nextDataLoading} fullWidth center disabled={!canLoadNextData}>
                {text}
            </LemonButton>
        </div>
    )
}

export function LoadPreviewText({ localResponse }: { localResponse?: Record<string, any> | null }): JSX.Element {
    const {
        response: dataNodeResponse,
        hasMoreData,
        responseLoading,
        nextQuery,
        nextDataLoading,
    } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    const response = dataNodeResponse ?? localResponse

    if (responseLoading) {
        return <div />
    }

    const resultCount = response && 'results' in response ? response?.results?.length ?? 0 : 0
    const isSingleEntry = resultCount === 1
    const showFirstPrefix = hasMoreData && resultCount > 1

    const lastRefreshTimeUtc: string | null | undefined =
        response && 'last_refresh' in response ? response['last_refresh'] : null

    return (
        <div className="flex flex-row items-center gap-2">
            <span>
                {showFirstPrefix ? 'Limited to the first ' : 'Showing '}
                {isSingleEntry ? 'one row' : `${resultCount} rows`}
            </span>
            {nextQuery && (
                <LemonButton
                    className="my-2"
                    onClick={loadNextData}
                    loading={nextDataLoading}
                    size="xsmall"
                    type="secondary"
                >
                    Load more
                </LemonButton>
            )}
            {lastRefreshTimeUtc && (
                <>
                    <span>|</span>
                    <TZLabel noStyles time={lastRefreshTimeUtc} />
                </>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'

import { DEFAULT_PAGE_SIZE } from '../DataVisualization/Components/Table'

interface LoadNextProps {
    query: DataNode
    nouns?: [string, string]
    /** The table shows each result row as a column, so the count must not read as visible rows */
    isTransposed?: boolean
}

function showingAllText(numberOfRows: number, isTransposed: boolean): string {
    if (numberOfRows === 1) {
        return isTransposed ? 'Showing one row as a column' : 'Showing one entry'
    }
    return isTransposed ? `Showing all ${numberOfRows} rows as columns` : `Showing all ${numberOfRows} entries`
}

export function LoadNext({ query, nouns = ['entry', 'entries'], isTransposed = false }: LoadNextProps): JSX.Element {
    const { canLoadNextData, nextDataLoading, numberOfRows, hasMoreData, dataLimit } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    const text = useMemo(() => {
        // if hogql based viz, show a different text
        if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
            // No data limit means the user is controlling the pagination
            if (!dataLimit) {
                if (numberOfRows && numberOfRows <= DEFAULT_PAGE_SIZE) {
                    return showingAllText(numberOfRows, isTransposed)
                }
                // If the number of rows is greater than the default page size, it's handled by pagination component
                return ''
            }
            if (numberOfRows && numberOfRows < dataLimit) {
                return showingAllText(numberOfRows, isTransposed)
            }
            return `Default limit of ${dataLimit} rows reached`
        } else if (isHogQLQuery(query) && !canLoadNextData && hasMoreData && dataLimit) {
            return `Default limit of ${dataLimit} rows reached. Try adding a LIMIT clause to adjust.`
        }
        const noun = numberOfRows === 1 ? nouns[0] : nouns[1]
        let result = `Showing ${
            hasMoreData && (numberOfRows ?? 0) > 1 ? 'first ' : canLoadNextData || numberOfRows === 1 ? '' : 'all '
        }${numberOfRows === 1 ? 'one' : numberOfRows} ${noun}`
        if (canLoadNextData) {
            result += nextDataLoading ? ' – loading more…' : ' – click to load more'
        } else if (hasMoreData) {
            result += ' – reached the end of results'
        }
        return result
    }, [query, dataLimit, numberOfRows, canLoadNextData, nextDataLoading, hasMoreData, nouns, isTransposed])

    // pagination component exists
    if (
        isDataVisualizationNode(query) &&
        isHogQLQuery(query.source) &&
        !dataLimit &&
        (!numberOfRows || numberOfRows > DEFAULT_PAGE_SIZE)
    ) {
        return <></>
    }

    return (
        <div className="m-2 flex items-center">
            <LemonButton onClick={loadNextData} loading={nextDataLoading} fullWidth center disabled={!canLoadNextData}>
                {text}
            </LemonButton>
        </div>
    )
}

export function LoadPreviewText({ localResponse }: { localResponse?: Record<string, any> | null }): JSX.Element {
    const { response: dataNodeResponse, hasMoreData, responseLoading } = useValues(dataNodeLogic)

    const response = dataNodeResponse ?? localResponse

    if (responseLoading) {
        return <div />
    }

    const resultCount = response && 'results' in response ? (response.results?.length ?? 0) : 0
    const isSingleEntry = resultCount === 1
    const showFirstPrefix = hasMoreData && resultCount > 1

    const lastRefreshTimeUtc: string | null | undefined =
        response && 'last_refresh' in response ? response['last_refresh'] : null

    return (
        <>
            <span>
                {showFirstPrefix ? 'Limited to the first ' : 'Showing '}
                {isSingleEntry ? 'one row' : `${resultCount} rows`}
            </span>
            {lastRefreshTimeUtc && (
                <>
                    <span className="ml-2 mr-2">|</span>
                    <TZLabel noStyles time={lastRefreshTimeUtc} />
                </>
            )}
        </>
    )
}

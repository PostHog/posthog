import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useMemo } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema'
import { isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'

import { DEFAULT_PAGE_SIZE } from '../DataVisualization/Components/Table'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { canLoadNextData, nextDataLoading, numberOfRows, hasMoreData, dataLimit } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    const text = useMemo(() => {
        // if hogql based viz, show a different text
        if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
            // No data limit means the user is controlling the pagination
            if (!dataLimit) {
                if (numberOfRows && numberOfRows <= DEFAULT_PAGE_SIZE) {
                    return `Showing ${numberOfRows === 1 ? '' : 'all'} ${numberOfRows === 1 ? 'one' : numberOfRows} ${
                        numberOfRows === 1 ? 'entry' : 'entries'
                    }`
                }
                // If the number of rows is greater than the default page size, it's handled by pagination component
                return ''
            }
            return `Default limit of ${dataLimit} rows reached`
        } else if (isHogQLQuery(query) && !canLoadNextData && hasMoreData && dataLimit) {
            return `Default limit of ${dataLimit} rows reached. Try adding a LIMIT clause to adjust.`
        }
        let result = `Showing ${
            hasMoreData && (numberOfRows ?? 0) > 1 ? 'first ' : canLoadNextData || numberOfRows === 1 ? '' : 'all '
        }${numberOfRows === 1 ? 'one' : numberOfRows} ${numberOfRows === 1 ? 'entry' : 'entries'}`
        if (canLoadNextData) {
            result += '. Click to load more.'
        } else if (hasMoreData) {
            result += '. Reached the end of results.'
        }
        return result
    }, [query, dataLimit, numberOfRows, canLoadNextData, hasMoreData])

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

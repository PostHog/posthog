import { useLayoutEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic, urlForResult } from './searchBarLogic'
import { SearchResult as SearchResultType } from './types'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { ResultDescription, ResultName } from 'lib/components/CommandBar/SearchResult'
import { NodeKind } from '~/queries/schema'
import { Query } from '~/queries/Query/Query'

export const SearchResultPreview = (): JSX.Element | null => {
    const { activeResultIndex, filterSearchResults } = useValues(searchBarLogic)

    if (!filterSearchResults || filterSearchResults.length === 0) {
        return null
    }

    const result = filterSearchResults[activeResultIndex]
    console.debug('result', result, activeResultIndex, filterSearchResults)
    const { type } = result

    return (
        <div className="border bg-bg-light rounded p-6">
            <div>{resultTypeToName[type]}</div>
            <div className="text-text-3000 font-bold text-lg">
                <ResultName result={result} />
            </div>
            <div className="mt-2 text-muted">
                <ResultDescription result={result} />
                {/*{type === 'insight' && <Query query={{ kind: NodeKind.SavedInsightNode, shortId: result.id }} />}*/}
            </div>

            {/*<pre>{JSON.stringify(result, null, 2)}</pre>*/}
        </div>
    )
}

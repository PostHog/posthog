import { useActions, useValues } from 'kea'

import { ResultDescription, ResultName } from 'lib/components/CommandBar/SearchResult'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { tabToName } from './constants'
import { searchBarLogic, urlForResult } from './searchBarLogic'

export const SearchResultPreview = (): JSX.Element | null => {
    const { activeResultIndex, combinedSearchResults, combinedSearchLoading } = useValues(searchBarLogic)
    const { openResult } = useActions(searchBarLogic)

    if (combinedSearchLoading) {
        return (
            <div className="border bg-surface-primary rounded p-4 md:p-6 min-h-[245px] flex flex-col gap-y-2">
                <LemonSkeleton className="w-[45px] h-4" />
                <LemonSkeleton className="w-[150px] h-4" />
                <LemonSkeleton className="w-[300px] h-4" />
            </div>
        )
    }

    if (!combinedSearchResults || combinedSearchResults.length === 0) {
        return null
    }

    const result = combinedSearchResults[activeResultIndex]

    if (!result) {
        return null
    }

    return (
        <div className="border bg-surface-primary rounded p-4 md:p-6">
            <div className="deprecated-space-y-4">
                <div>
                    <div>{tabToName[result.type as keyof typeof tabToName]}</div>
                    <div className="text-text-3000 font-bold text-lg">
                        <ResultName result={result} />
                    </div>
                    <span className="text-[var(--trace-3000)] text-xs break-all">
                        {location.host}
                        <span className="text-muted-3000">{urlForResult(result)}</span>
                    </span>
                    <div className="mt-2 text-secondary">
                        <ResultDescription result={result} />
                    </div>
                </div>
                <div className="grid grid-cols-[auto_1fr] items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            openResult(activeResultIndex)
                        }}
                        aria-label="Open search result"
                    >
                        <span className="mr-1">Open</span> <KeyboardShortcut enter />
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

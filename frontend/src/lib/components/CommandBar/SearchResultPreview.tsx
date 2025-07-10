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
            <div className="bg-surface-primary flex min-h-[245px] flex-col gap-y-2 rounded border p-4 md:p-6">
                <LemonSkeleton className="h-4 w-[45px]" />
                <LemonSkeleton className="h-4 w-[150px]" />
                <LemonSkeleton className="h-4 w-[300px]" />
            </div>
        )
    }

    if (!combinedSearchResults || combinedSearchResults.length === 0) {
        return null
    }

    const result = combinedSearchResults[activeResultIndex]

    return (
        <div className="bg-surface-primary rounded border p-4 md:p-6">
            <div className="deprecated-space-y-4">
                <div>
                    <div>{tabToName[result.type as keyof typeof tabToName]}</div>
                    <div className="text-text-3000 text-lg font-bold">
                        <ResultName result={result} />
                    </div>
                    <span className="break-all text-xs text-[var(--trace-3000)]">
                        {location.host}
                        <span className="text-muted-3000">{urlForResult(result)}</span>
                    </span>
                    <div className="text-secondary mt-2">
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

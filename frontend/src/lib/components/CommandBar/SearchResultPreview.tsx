import { useActions, useValues } from 'kea'
import { ResultDescription, ResultName } from 'lib/components/CommandBar/SearchResult'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { tabToName } from './constants'
import { searchBarLogic, urlForResult } from './searchBarLogic'

export const SearchResultPreview = (): JSX.Element | null => {
    const { activeResultIndex, combinedSearchResults } = useValues(searchBarLogic)
    const { openResult } = useActions(searchBarLogic)

    if (!combinedSearchResults || combinedSearchResults.length === 0) {
        return null
    }

    const result = combinedSearchResults[activeResultIndex]

    return (
        <div className="border bg-bg-light rounded p-4 md:p-6">
            <div className="space-y-4">
                <div>
                    <div>{tabToName[result.type as keyof typeof tabToName]}</div>
                    <div className="text-text-3000 font-bold text-lg">
                        <ResultName result={result} />
                    </div>
                    <span className="text-[var(--trace-3000)] text-xs break-all">
                        {location.host}
                        <span className="text-muted-3000">{urlForResult(result)}</span>
                    </span>
                    <div className="mt-2 text-muted">
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
                        tooltip={
                            <>
                                Open <KeyboardShortcut enter />
                            </>
                        }
                        aria-label="Open search result"
                    >
                        Open
                    </LemonButton>
                    <div>
                        <KeyboardShortcut enter /> Open
                    </div>
                </div>
            </div>
        </div>
    )
}

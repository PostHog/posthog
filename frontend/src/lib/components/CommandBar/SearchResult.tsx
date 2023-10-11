import { useEffect, useRef } from 'react'
import { useActions } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult as SearchResultType } from './types'

type SearchResultProps = {
    result: SearchResultType
    resultIndex: number
    focused: boolean
    keyboardFocused: boolean
}

const SearchResult = ({ result, resultIndex, focused, keyboardFocused }: SearchResultProps): JSX.Element => {
    const { onMouseEnterResult, onMouseLeaveResult } = useActions(searchBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (keyboardFocused) {
            ref.current?.scrollIntoView()
        }
    }, [keyboardFocused])

    return (
        <div
            className={`w-full pl-3 pr-2 ${
                focused ? 'bg-secondary-3000-hover' : 'bg-secondary-3000'
            } border-b cursor-pointer`}
            onMouseEnter={() => {
                onMouseEnterResult(resultIndex)
            }}
            onMouseLeave={() => {
                onMouseLeaveResult()
            }}
            onClick={() => {
                // if (isExecutable) {
                //     executeResult(result)
                // }
            }}
            ref={ref}
        >
            <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                <span className="text-muted-3000 text-xs">{resultTypeToName[result.type]}</span>
                <span className="text-text-3000">{result.name}</span>
                <span className="text-trace-3000 text-xs">
                    app.posthog.com/
                    <span className="text-muted-3000">
                        {result.type}/{result.pk}
                    </span>
                </span>
            </div>
        </div>
    )
}

export default SearchResult

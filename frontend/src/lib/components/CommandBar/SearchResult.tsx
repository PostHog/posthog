import { useEffect, useRef } from 'react'
import { useActions } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic, urlForResult } from './searchBarLogic'
import { SearchResult as SearchResultType } from './types'

type SearchResultProps = {
    result: SearchResultType
    resultIndex: number
    focused: boolean
    keyboardFocused: boolean
}

const SearchResult = ({ result, resultIndex, focused, keyboardFocused }: SearchResultProps): JSX.Element => {
    const { onMouseEnterResult, onMouseLeaveResult, openActiveResult } = useActions(searchBarLogic)

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
                openActiveResult()
            }}
            ref={ref}
        >
            <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                <span className="text-muted-3000 text-xs">{resultTypeToName[result.type]}</span>
                <span className="text-text-3000">{result.name}</span>
                <span className="text-trace-3000 text-xs">
                    {location.host}
                    <span className="text-muted-3000">{urlForResult(result)}</span>
                </span>
            </div>
        </div>
    )
}

export default SearchResult

import { useLayoutEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'

import { resultTypeToName } from './constants'
import { searchBarLogic, urlForResult } from './searchBarLogic'
import { SearchResult as SearchResultType } from './types'
import { LemonSkeleton } from '@posthog/lemon-ui'

type SearchResultProps = {
    result: SearchResultType
    resultIndex: number
    focused: boolean
    keyboardFocused: boolean
}

const SearchResult = ({ result, resultIndex, focused, keyboardFocused }: SearchResultProps): JSX.Element => {
    const { isAutoScrolling } = useValues(searchBarLogic)
    const { onMouseEnterResult, onMouseLeaveResult, openResult, setIsAutoScrolling } = useActions(searchBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    useLayoutEffect(() => {
        if (keyboardFocused) {
            // :HACKY: This uses the non-standard scrollIntoViewIfNeeded api
            // to improve scroll behaviour. Change to scrollIntoView({ scrollMode: 'if-needed' })
            // once available.
            if ((ref.current as any)?.scrollIntoViewIfNeeded) {
                ;(ref.current as any).scrollIntoViewIfNeeded(false)
            } else {
                ref.current?.scrollIntoView()
            }

            // set scrolling state to prevent mouse enter/leave events during
            // keyboard navigation
            setIsAutoScrolling(true)
            setTimeout(() => {
                setIsAutoScrolling(false)
            }, 50)
        }
    }, [keyboardFocused])

    return (
        <div
            className={`w-full pl-3 pr-2 ${
                focused ? 'bg-secondary-3000-hover' : 'bg-secondary-3000'
            } border-b cursor-pointer`}
            onMouseEnter={() => {
                if (isAutoScrolling) {
                    return
                }
                onMouseEnterResult(resultIndex)
            }}
            onMouseLeave={() => {
                if (isAutoScrolling) {
                    return
                }
                onMouseLeaveResult()
            }}
            onClick={() => {
                openResult(resultIndex)
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

export const SearchResultSkeleton = (): JSX.Element => (
    <div className="w-full pl-3 pr-2 bg-secondary-3000 border-b">
        <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
            <LemonSkeleton className="w-32 opacity-75" height={3} />
            <LemonSkeleton className="w-80" />
            <LemonSkeleton className="w-100 opacity-75" height={3} />
        </div>
    </div>
)

export default SearchResult

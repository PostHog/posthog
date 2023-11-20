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

export const SearchResult = ({ result, resultIndex, focused, keyboardFocused }: SearchResultProps): JSX.Element => {
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
                focused ? 'bg-accent-3000' : 'bg-bg-light'
            } border-r border-b cursor-pointer`}
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
                <span className="text-text-3000 font-bold">
                    <ResultName result={result} />
                </span>
                <span className="text-trace-3000 text-xs">
                    {location.host}
                    <span className="text-muted-3000">{urlForResult(result)}</span>
                </span>
            </div>
        </div>
    )
}

export const SearchResultSkeleton = (): JSX.Element => (
    <div className="px-5 py-4 w-full space-y-1.5 flex flex-col items-start bg-bg-light border-b">
        <LemonSkeleton className="w-32 opacity-75 h-3" />
        <LemonSkeleton className="w-80 h-3.5" />
        <LemonSkeleton className="w-100 opacity-75 h-3" />
    </div>
)

type ResultNameProps = {
    result: SearchResultType
}

export const ResultName = ({ result }: ResultNameProps): JSX.Element | null => {
    const { type, extra_fields } = result
    if (type === 'insight') {
        return extra_fields.name ? <span>{extra_fields.name}</span> : <i>{extra_fields.derived_name}</i>
    } else if (type === 'feature_flag') {
        return <span>{extra_fields.key}</span>
    } else if (type === 'notebook') {
        return <span>{extra_fields.title}</span>
    } else {
        return <span>{extra_fields.name}</span>
    }
}

export const ResultDescription = ({ result }: ResultNameProps): JSX.Element | null => {
    const { type, extra_fields } = result
    if (type === 'feature_flag') {
        return extra_fields.name && extra_fields.name !== extra_fields.key ? (
            <span>{extra_fields.name}</span>
        ) : (
            <i>No description.</i>
        )
    } else if (type === 'notebook') {
        return <span className="whitespace-pre">{extra_fields.text_content}</span>
    } else {
        return extra_fields.description ? <span>{extra_fields.description}</span> : <i>No description.</i>
    }
}

import { useLayoutEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'

import { resultTypeToName } from './constants'
import { actionBarLogic } from './actionBarLogic'
import { SearchResult as SearchResultType } from './types'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'

type SearchResultProps = {
    result: CommandResultDisplayable
    resultIndex: number
    focused: boolean
    keyboardFocused: boolean
}

const ActionResult = ({ result, resultIndex, focused, keyboardFocused }: SearchResultProps): JSX.Element => {
    // const { scrolling } = useValues(actionBarLogic)
    const {
        // onMouseEnterResult,
        // onMouseLeaveResult,
        openResult,
        // setScrolling,
    } = useActions(actionBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    // useLayoutEffect(() => {
    //     if (keyboardFocused) {
    //         // :HACKY: This uses the non-standard scrollIntoViewIfNeeded api
    //         // to improve scroll behaviour. Change to scrollIntoView({ scrollMode: 'if-needed' })
    //         // once available.
    //         if ((ref.current as any)?.scrollIntoViewIfNeeded) {
    //             ;(ref.current as any).scrollIntoViewIfNeeded(false)
    //         } else {
    //             ref.current?.scrollIntoView()
    //         }

    //         // set scrolling state to prevent mouse enter/leave events during
    //         // keyboard navigation
    //         setScrolling(true)
    //         setTimeout(() => {
    //             setScrolling(false)
    //         }, 50)
    //     }
    // }, [keyboardFocused])

    return (
        <div
            className={`w-full pl-3 pr-2 ${
                focused ? 'bg-secondary-3000-hover' : 'bg-secondary-3000'
            } border-b cursor-pointer`}
            // onMouseEnter={() => {
            //     if (scrolling) {
            //         return
            //     }
            //     onMouseEnterResult(resultIndex)
            // }}
            // onMouseLeave={() => {
            //     if (scrolling) {
            //         return
            //     }
            //     onMouseLeaveResult()
            // }}
            onClick={() => {
                openResult(resultIndex)
            }}
            ref={ref}
        >
            <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                <span className="text-muted-3000 text-xs">{result.source.scope}</span>
                <span className="text-text-3000">{result.display}</span>
            </div>
        </div>
    )
}

export default ActionResult

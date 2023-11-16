import { useEffect, useRef } from 'react'
import { useActions } from 'kea'

import { actionBarLogic } from './actionBarLogic'
import { getNameFromActionScope } from './utils'
import { CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'

type SearchResultProps = {
    result: CommandResultDisplayable
    focused: boolean
}

const ActionResult = ({ result, focused }: SearchResultProps): JSX.Element => {
    const { executeResult, onMouseEnterResult, onMouseLeaveResult } = useActions(actionBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)
    const isExecutable = !!result.executor

    useEffect(() => {
        if (focused) {
            ref.current?.scrollIntoView()
        }
    }, [focused])

    return (
        <div className={`border-l-4 ${isExecutable ? 'border-primary' : ''}`}>
            <div
                className={`w-full pl-3 pr-2 ${
                    focused ? 'bg-secondary-3000-hover' : 'bg-secondary-3000'
                } border-b cursor-pointer`}
                onMouseEnter={() => {
                    onMouseEnterResult(result.index)
                }}
                onMouseLeave={() => {
                    onMouseLeaveResult()
                }}
                onClick={() => {
                    if (isExecutable) {
                        executeResult(result)
                    }
                }}
                ref={ref}
            >
                <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                    {result.source.scope && (
                        <span className="text-muted-3000 text-xs">{getNameFromActionScope(result.source.scope)}</span>
                    )}
                    <span className="text-text-3000">{result.display}</span>
                </div>
            </div>
        </div>
    )
}

export default ActionResult

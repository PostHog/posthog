import clsx from 'clsx'
import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { actionBarLogic } from './actionBarLogic'

type SearchResultProps = {
    result: CommandResultDisplayable
    focused: boolean
}

export const ActionResult = ({ result, focused }: SearchResultProps): JSX.Element => {
    const { executeResult } = useActions(actionBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)
    const isExecutable = !!result.executor

    useEffect(() => {
        if (focused) {
            ref.current?.scrollIntoView()
        }
    }, [focused])

    return (
        <div className={clsx('border-l-4', focused ? 'border-accent' : !isExecutable ? 'border-transparent' : null)}>
            <div
                className={`flex items-center w-full px-2 hover:bg-surface-secondary ${
                    focused ? 'bg-surface-secondary' : 'bg-surface-primary'
                } border-b cursor-pointer`}
                onClick={() => {
                    if (isExecutable) {
                        executeResult(result)
                    }
                }}
                ref={ref}
            >
                <div className="px-2 py-3 w-full gap-y-0.5 flex items-center">
                    <result.icon className="text-muted-3000" />
                    <span className="ml-2 text-text-3000 font-bold">{result.display}</span>
                </div>
                {focused && <div className="shrink-0 text-primary-3000">Run command</div>}
            </div>
        </div>
    )
}

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
                className={`hover:bg-surface-secondary flex w-full items-center px-2 ${
                    focused ? 'bg-surface-secondary' : 'bg-surface-primary'
                } cursor-pointer border-b`}
                onClick={() => {
                    if (isExecutable) {
                        executeResult(result)
                    }
                }}
                ref={ref}
            >
                <div className="flex w-full items-center gap-y-0.5 px-2 py-3">
                    <result.icon className="text-muted-3000" />
                    <span className="text-text-3000 ml-2 font-bold">{result.display}</span>
                </div>
                {focused && <div className="text-primary-3000 shrink-0">Run command</div>}
            </div>
        </div>
    )
}

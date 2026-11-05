import React from 'react'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { cn } from 'lib/utils/css-classes'

interface RenderKeybindProps {
    keybind: string[][]
    className?: string
    minimal?: boolean
}

export function RenderKeybind({ keybind, className, minimal }: RenderKeybindProps): JSX.Element {
    return (
        <span className={cn('inline-flex items-center gap-1', className)}>
            {keybind.map((keybindOption, index) => {
                const isSequence = keybindOption.includes('then')
                if (isSequence) {
                    const keys = keybindOption.filter((k) => k !== 'then')
                    return (
                        <React.Fragment key={index}>
                            {index > 0 && <span className="mx-1 text-xxs opacity-75">or</span>}
                            {keys.map((key, keyIndex) => (
                                <React.Fragment key={key}>
                                    {keyIndex > 0 && <span className="mx-1 opacity-50 lowercase text-xxs">then</span>}
                                    <kbd className="KeyboardShortcut gap-x-0.5 text-xxs">{key}</kbd>
                                </React.Fragment>
                            ))}
                        </React.Fragment>
                    )
                }
                return (
                    <React.Fragment key={index}>
                        {index > 0 && <span className="mx-1 text-xxs opacity-75">or</span>}
                        <KeyboardShortcut
                            {...Object.fromEntries(keybindOption.map((key: string) => [key, true]))}
                            className="text-xs"
                            minimal={minimal}
                        />
                    </React.Fragment>
                )
            })}
        </span>
    )
}

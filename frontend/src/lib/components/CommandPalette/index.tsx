import { useOutsideClickHandler, isMacintosh } from 'lib/utils'
import React, { useCallback, useEffect, useState } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { useCommands } from './commandLogic'
import { globalCommands } from './globalCommands'
import { CommandSearch } from './CommandSearch'

export function CommandPalette(): JSX.Element | false {
    const boxRef = useRef<HTMLDivElement | null>(null)

    const [isBoxShown, setIsBoxShown] = useState<boolean>(false)

    const closeBox = useCallback(() => {
        setIsBoxShown(false)
    }, [setIsBoxShown])

    useHotkeys(isMacintosh() ? 'cmd+k' : 'ctrl+k', () => {
        setIsBoxShown((prevShowBox) => !prevShowBox)
    })

    useHotkeys('esc', () => {
        closeBox()
    })

    useOutsideClickHandler(boxRef, () => {
        closeBox()
    })

    useCommands(globalCommands)

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isBoxShown ? 'hidden' : ''
    }, [isBoxShown])

    return (
        isBoxShown && (
            <div
                ref={boxRef}
                style={{
                    zIndex: 9999,
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    width: 700,
                    height: 400,
                    boxShadow: '0 0 20px 15px rgba(0, 0, 0, 0.05)',
                    backgroundColor: 'white',
                    borderRadius: 10,
                }}
            >
                <CommandSearch></CommandSearch>
            </div>
        )
    )
}

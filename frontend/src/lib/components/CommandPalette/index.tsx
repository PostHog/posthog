import { useOutsideClickHandler } from 'lib/utils'
import React, { useEffect } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { CommandSearch } from './CommandSearch'

interface BoxProps {
    visible: boolean
    onClickOutside: () => void
    onClose: () => void
}

export function CommandPalette({ visible, onClose }: BoxProps): JSX.Element | false {
    const boxRef = useRef<HTMLDivElement | null>(null)

    useHotkeys('esc', () => {
        onClose()
    })

    useOutsideClickHandler(boxRef, () => {
        onClose()
    })

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = visible ? 'hidden' : ''
    }, [visible])

    return (
        visible && (
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
                <CommandSearch onClose={onClose}></CommandSearch>
            </div>
        )
    )
}

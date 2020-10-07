import React, { useEffect, useState } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'

export function CommandPaletteContainer({ children }: React.PropsWithChildren<unknown>): JSX.Element {
    const [showBox, setShowBox] = useState<boolean>(false)

    useHotkeys(isMacintosh() ? 'cmd+k' : 'ctrl+k', () => {
        setShowBox((prevShowBox) => !prevShowBox)
    })

    const closeBox = (): void => {
        setShowBox(false)
    }

    return (
        <div>
            <CommandPalette visible={showBox} onClickOutside={closeBox} />
            {children}
        </div>
    )
}

interface BoxProps {
    visible: boolean
    onClickOutside: () => void
}

function CommandPalette({ visible, onClickOutside }: BoxProps): JSX.Element {
    const boxRef = useRef()

    const _onClickOutside = (event: MouseEvent): void => {
        if (!boxRef.current?.contains(event.target) && visible) {
            onClickOutside()
        }
    }

    useEffect(() => {
        document.addEventListener('mousedown', _onClickOutside)
        return () => {
            document.removeEventListener('mousedown', _onClickOutside)
        }
    }, [visible])

    useEffect(() => {
        if (visible) document.body.style.overflow = 'hidden'
        else document.body.style.overflow = 'unset'
    }, [visible])

    return visible ? (
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
        />
    ) : (
        <></>
    )
}

function isMacintosh(): boolean {
    return navigator.platform.indexOf('Mac') > -1
}

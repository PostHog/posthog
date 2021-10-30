import { Button } from 'antd'
import { ButtonProps } from 'antd/lib/button'
import React from 'react'
import { HotKeys } from '~/types'
import './HotkeyButton.scss'

interface HotkeyButtonProps extends ButtonProps {
    hotkey: HotKeys
}

export function HotkeyButton({ hotkey, children, ...props }: HotkeyButtonProps): JSX.Element {
    return (
        <span className="hotkey-button">
            <Button {...props}>
                {children} <span className="hotkey">{hotkey}</span>
            </Button>
        </span>
    )
}

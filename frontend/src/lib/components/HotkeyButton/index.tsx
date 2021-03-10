import { Button, ButtonProps } from 'antd'
import React from 'react'
import { Keys } from '~/types'
import './index.scss'

interface HotKeyButtonProps extends ButtonProps {
    hotkey: Keys
}

export function HotkeyButton({ hotkey, children, ...props }: HotKeyButtonProps): JSX.Element {
    return (
        <span className="hotkey-button">
            <Button {...props}>
                {children} <span className="hotkey">{hotkey}</span>
            </Button>
        </span>
    )
}

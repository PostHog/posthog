import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import React from 'react'
import { IconClose } from '../icons'
import './LemonSnack.scss'

export interface LemonSnackProps {
    children?: JSX.Element | string
    icon?: React.ReactElement
    disabled?: boolean
    onClose?: () => void
    'data-attr'?: string
}

export function LemonSnack({ icon, children, disabled, onClose }: LemonSnackProps): JSX.Element {
    return (
        <span
            className={clsx('LemonSnack', {
                'LemonSnack--disabled': disabled,
            })}
        >
            {icon}
            {children}

            {onClose ? <LemonButton type="stealth" size="small" icon={<IconClose />} onClick={onClose} /> : undefined}
        </span>
    )
}

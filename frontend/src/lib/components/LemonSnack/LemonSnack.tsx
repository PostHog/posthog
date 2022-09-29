import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import React from 'react'
import { IconClose } from '../icons'
import './LemonSnack.scss'

export interface LemonSnackProps {
    children?: React.ReactNode
    onClose?: () => void
    title?: string
    wrap?: boolean
    'data-attr'?: string
}

export function LemonSnack({ children, wrap, onClose, title }: LemonSnackProps): JSX.Element {
    return (
        <span
            className={clsx('LemonSnack', {
                'LemonSnack--wrap': wrap,
            })}
        >
            <span className="LemonSnack__inner" title={title ?? (typeof children === 'string' ? children : undefined)}>
                {children}
            </span>

            {onClose ? (
                <span className="LemonSnack__close">
                    <LemonButton status="stealth" size="small" noPadding icon={<IconClose />} onClick={onClose} />
                </span>
            ) : undefined}
        </span>
    )
}

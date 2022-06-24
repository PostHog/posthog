import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import React from 'react'
import { IconClose } from '../icons'
import './LemonSnack.scss'

export interface LemonSnackProps {
    children?: React.ReactNode
    disabled?: boolean
    onClose?: () => void
    'data-attr'?: string
}

export function LemonSnack({ children, disabled, onClose }: LemonSnackProps): JSX.Element {
    return (
        <span
            className={clsx('LemonSnack', {
                'LemonSnack--disabled': disabled,
            })}
        >
            <span className="LemonSnack__inner">
                {children}

                {onClose ? (
                    <span className="LemonSnack__close">
                        <LemonButton type="stealth" size="small" icon={<IconClose />} onClick={onClose} />
                    </span>
                ) : undefined}
            </span>
        </span>
    )
}

import clsx from 'clsx'
import React from 'react'
import { LemonRow, LemonRowProps } from '../LemonRow'
import './LemonButton.scss'

export interface LemonButtonProps extends Omit<LemonRowProps<'button'>, 'tag'> {
    type?: 'default' | 'primary' | 'stealth'
}

/** Styled button. */
export function LemonButton({
    children,
    icon,
    type = 'default',
    align,
    ...buttonProps
}: LemonButtonProps): JSX.Element {
    return (
        <LemonRow
            tag="button"
            className={clsx('LemonButton', type !== 'default' && `LemonButton--${type}`)}
            icon={icon}
            type="button"
            align={align}
            {...buttonProps}
        >
            {children}
        </LemonRow>
    )
}

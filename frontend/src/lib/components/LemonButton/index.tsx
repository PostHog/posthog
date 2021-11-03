import clsx from 'clsx'
import React from 'react'
import { LemonRow, LemonRowProps } from '../LemonRow'
import { Link } from '../Link'
import './LemonButton.scss'

export interface LemonButtonProps extends Omit<LemonRowProps<'button'>, 'tag' | 'onClick'> {
    type?: 'default' | 'primary' | 'stealth' | 'highlighted'
    /** `onClick` of type `string` means a link. */
    onClick?: LemonRowProps<'button'>['onClick'] | string
    tooltip?: string
}

/** Styled button. */
export function LemonButton({
    children,
    icon,
    type = 'default',
    className,
    ...buttonProps
}: LemonButtonProps): JSX.Element {
    const { onClick, ...buttonPropsInternal } = buttonProps
    let onClickInternal: LemonRowProps<'button'>['onClick'] | undefined
    let link: string | undefined
    if (typeof onClick === 'string') {
        link = onClick
    } else {
        onClickInternal = onClick
    }
    const row = (
        <LemonRow
            tag="button"
            className={clsx('LemonButton', type !== 'default' && `LemonButton--${type}`, className)}
            icon={icon}
            type="button"
            onClick={onClickInternal}
            {...buttonPropsInternal}
        >
            {children}
        </LemonRow>
    )
    return link ? <Link to={link}>{row}</Link> : row
}

export type SideAction = Pick<LemonButtonProps, 'onClick' | 'icon' | 'type' | 'tooltip'>
export interface LemonButtonWithSideActionProps extends LemonButtonProps {
    sideAction?: SideAction
}

/** Styled button with a side action on the right. */
export function LemonButtonWithSideAction({ sideAction, ...buttonProps }: LemonButtonWithSideActionProps): JSX.Element {
    return sideAction ? (
        <div className="LemonButtonWithSideAction">
            <LemonButton {...buttonProps} />
            <LemonButton className="side-button" compact {...sideAction} />
        </div>
    ) : (
        <LemonButton {...buttonProps} />
    )
}

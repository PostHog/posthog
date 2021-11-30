import clsx from 'clsx'
import React from 'react'
import { IconArrowDropDown } from '../icons'
import { LemonRow, LemonRowProps, LemonRowPropsBase } from '../LemonRow'
import { Link } from '../Link'
import { Popup, PopupProps } from '../Popup/Popup'
import './LemonButton.scss'

export type LemonButtonPopup = Omit<PopupProps, 'children'>

export interface LemonButtonPropsBase extends Omit<LemonRowPropsBase<'button'>, 'tag' | 'type' | 'ref'> {
    type?: 'default' | 'primary' | 'stealth' | 'highlighted'
    /** URL to link to. */
    to?: string
    popup?: LemonButtonPopup
}

/** Note that a LemonButton can be compact OR have a sideIcon, but not both at once. */
export type LemonButtonProps =
    | (LemonButtonPropsBase & {
          sideIcon?: null
          compact?: boolean
      })
    | (LemonButtonPropsBase & {
          sideIcon?: React.ReactElement | null
          compact?: false
      })

/** Styled button. */
function LemonButtonInternal(
    { children, type = 'default', className, popup, to, ...buttonProps }: LemonButtonProps,
    ref: React.Ref<JSX.IntrinsicElements['button']>
): JSX.Element {
    const rowProps: LemonRowProps<'button'> = {
        tag: 'button',
        className: clsx('LemonButton', type !== 'default' && `LemonButton--${type}`, className),
        type: 'button',
        ...buttonProps,
    }
    if (popup && !rowProps.compact && !rowProps.sideIcon) {
        rowProps.sideIcon = <IconArrowDropDown />
    }
    let workingButton = (
        <LemonRow {...rowProps} ref={ref}>
            {children}
        </LemonRow>
    )
    if (to) {
        workingButton = <Link to={to}>{workingButton}</Link>
    }
    if (popup) {
        workingButton = <Popup {...popup}>{workingButton}</Popup>
    }
    return workingButton
}
export const LemonButton = React.forwardRef(LemonButtonInternal)

export type SideAction = Pick<LemonButtonProps, 'onClick' | 'popup' | 'to' | 'icon' | 'type' | 'tooltip' | 'data-attr'>

/** A LemonButtonWithSideAction can neither be compact nor have a sideIcon - instead it has a clickable sideAction. */
export interface LemonButtonWithSideActionProps extends LemonButtonPropsBase {
    sideAction: SideAction
}

/**
 * Styled button with a side action on the right.
 * We can't use `LemonRow`'s `sideIcon` prop because putting `onClick` on it clashes with the parent`s `onClick`.
 */
export function LemonButtonWithSideAction({ sideAction, ...buttonProps }: LemonButtonWithSideActionProps): JSX.Element {
    return (
        <div className="LemonButtonWithSideAction">
            {/* Bogus `sideIcon` div prevents overflow under the side button. */}
            <LemonButton {...buttonProps} sideIcon={<div />} />{' '}
            <LemonButton className="side-button" compact {...sideAction} />
        </div>
    )
}

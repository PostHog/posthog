import clsx from 'clsx'
import React from 'react'
import { IconArrowDropDown } from '../icons'
import { LemonRow, LemonRowProps, LemonRowPropsBase } from '../LemonRow'
import { Link } from '../Link'
import { Popup, PopupProps } from '../Popup/Popup'
import './LemonButton.scss'

export interface LemonButtonPopup extends Pick<PopupProps, 'overlay' | 'visible' | 'onClickOutside'> {
    onClickReference: () => void
}

export interface LemonButtonPropsBase extends Omit<LemonRowPropsBase<'button'>, 'tag' | 'onClick' | 'type' | 'ref'> {
    type?: 'default' | 'primary' | 'stealth' | 'highlighted'
    /** `onClick` of type `string` means a link, while a LemonButtonPopup enables a Popup. */
    onClick?: LemonRowPropsBase<'button'>['onClick'] | LemonButtonPopup | string
}

/** Note that a LemonButton can be compact OR have a sideIcon, but not both at once. */
export type LemonButtonProps =
    | (LemonButtonPropsBase & {
          sideIcon?: null
          compact?: boolean
      })
    | (LemonButtonPropsBase & {
          sideIcon?: React.ReactElement
          compact?: false
      })

/** Styled button. */
function LemonButtonInternal(
    { children, icon, type = 'default', className, onClick, ...buttonProps }: LemonButtonProps,
    ref: React.Ref<JSX.IntrinsicElements['button']>
): JSX.Element {
    const rowProps: LemonRowProps<'button'> = {
        tag: 'button',
        className: clsx('LemonButton', type !== 'default' && `LemonButton--${type}`, className),
        icon,
        type: 'button',
        ...buttonProps,
    }
    switch (typeof onClick) {
        case 'string':
            return (
                <Link to={onClick}>
                    <LemonRow {...rowProps} ref={ref}>
                        {children}
                    </LemonRow>
                </Link>
            )
        case 'object':
            if (!rowProps.sideIcon) {
                rowProps.sideIcon = <IconArrowDropDown />
            }
            return (
                <Popup
                    visible={onClick.visible}
                    onClickOutside={onClick.onClickOutside}
                    overlay={onClick.overlay}
                    sameWidth
                >
                    <LemonRow onClick={onClick.onClickReference} {...rowProps} ref={ref}>
                        {children}
                    </LemonRow>
                </Popup>
            )
        default:
            return (
                <LemonRow onClick={onClick} {...rowProps} ref={ref}>
                    {children}
                </LemonRow>
            )
    }
}
export const LemonButton = React.forwardRef(LemonButtonInternal)

export type SideAction = Pick<LemonButtonProps, 'onClick' | 'icon' | 'type' | 'tooltip'>

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
            <LemonButton {...buttonProps} />
            <LemonButton className="side-button" compact {...sideAction} />
        </div>
    )
}

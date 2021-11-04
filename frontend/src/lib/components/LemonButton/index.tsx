import clsx from 'clsx'
import React from 'react'
import { IconArrowDropDown } from '../icons'
import { LemonRow, LemonRowPropsBase } from '../LemonRow'
import { Link } from '../Link'
import { Popup, PopupProps } from '../Popup/Popup'
import './LemonButton.scss'

export interface LemonButtonPropsBase extends Omit<LemonRowPropsBase<'button'>, 'tag' | 'onClick' | 'type' | 'ref'> {
    type?: 'default' | 'primary' | 'stealth' | 'highlighted'
    /** `onClick` of type `string` means a link. */
    onClick?: LemonRowPropsBase<'button'>['onClick'] | string
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
    const link = typeof onClick !== 'string' ? null : onClick
    const row = (
        <LemonRow
            tag="button"
            className={clsx('LemonButton', type !== 'default' && `LemonButton--${type}`, className)}
            icon={icon}
            type="button"
            {...buttonProps}
            onClick={typeof onClick !== 'string' ? onClick : undefined}
            ref={ref}
        >
            {children}
        </LemonRow>
    )
    return link ? <Link to={link}>{row}</Link> : row
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
export type LemonButtonWithPopupProps = Omit<LemonButtonPropsBase, 'onClick'> &
    Pick<PopupProps, 'overlay' | 'visible' | 'onClickOutside'> & {
        onClickReference: () => void
    }

/**
 * Styled button with a Popup on click.
 */
export function LemonButtonWithPopup({
    overlay,
    visible,
    onClickReference,
    onClickOutside,
    ...buttonProps
}: LemonButtonWithPopupProps): JSX.Element {
    return (
        <Popup visible={visible} onClickOutside={onClickOutside} overlay={overlay} sameWidth>
            <LemonButton onClick={onClickReference} sideIcon={<IconArrowDropDown />} {...buttonProps} />
        </Popup>
    )
}

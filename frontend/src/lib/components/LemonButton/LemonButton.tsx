import clsx from 'clsx'
import React, { useContext, useState } from 'react'
import { IconArrowDropDown, IconChevronRight } from '../icons'
import { LemonRow, LemonRowProps, LemonRowPropsBase, LemonSpacer } from '../LemonRow'
import { Link } from '../Link'
import { Popup, PopupProps, PopupContext } from '../Popup/Popup'
import './LemonButton.scss'

export type LemonButtonPopup = Omit<PopupProps, 'children'>
export interface LemonButtonPropsBase extends Omit<LemonRowPropsBase<'button'>, 'tag' | 'type' | 'ref'> {
    ref?: React.Ref<HTMLButtonElement>
    type?: 'default' | 'primary' | 'secondary' | 'tertiary' | 'stealth' | 'highlighted' | 'primary-alt'
    htmlType?: LemonRowPropsBase<'button'>['type']
    /** Whether the button should have transparent background in its base state (i.e. non-hover). */
    translucent?: boolean
    /** Whether hover style should be applied, signaling that the button is held active in some way. */
    active?: boolean
    /** URL to link to. */
    to?: string
}

export interface LemonButtonProps extends LemonButtonPropsBase {
    sideIcon?: React.ReactElement | null
    /** DEPRECATED: Use `LemonButtonWithPopup` instead. */
    popup?: LemonButtonPopup
}

/** Styled button. */
function LemonButtonInternal(
    {
        children,
        type = 'default',
        htmlType = 'button',
        translucent = false,
        active = false,
        className,
        popup,
        to,
        href,
        ...buttonProps
    }: LemonButtonProps,
    ref: React.Ref<JSX.IntrinsicElements['button']>
): JSX.Element {
    const rowProps: LemonRowProps<'button'> = {
        tag: 'button',
        className: clsx(
            'LemonButton',
            type !== 'default' && `LemonButton--${type}`,
            active && 'LemonButton--active',
            translucent && 'LemonButton--translucent',
            className
        ),
        type: htmlType,
        ...buttonProps,
    }
    if (popup && (children || !buttonProps.icon) && !rowProps.sideIcon) {
        rowProps.sideIcon = <IconArrowDropDown />
    }
    let workingButton = (
        <LemonRow {...rowProps} ref={ref}>
            {children}
        </LemonRow>
    )
    if (to) {
        workingButton = (
            <Link to={to} style={{ display: 'contents' }}>
                {workingButton}
            </Link>
        )
    }
    if (href) {
        workingButton = (
            <a href={href} style={{ display: 'contents' }} target="_blank" rel="noopener noreferrer">
                {workingButton}
            </a>
        )
    }
    if (popup) {
        workingButton = <Popup {...popup}>{workingButton}</Popup>
    }
    return workingButton
}
export const LemonButton = React.forwardRef(LemonButtonInternal) as typeof LemonButtonInternal

export type SideAction = Pick<
    LemonButtonProps,
    'onClick' | 'popup' | 'to' | 'disabled' | 'icon' | 'tooltip' | 'data-attr'
>

/** A LemonButtonWithSideAction can't have a sideIcon - instead it has a clickable sideAction. */
export interface LemonButtonWithSideActionProps extends LemonButtonPropsBase {
    sideAction: SideAction
}

/**
 * Styled button with a side action on the right.
 * We can't use `LemonRow`'s `sideIcon` prop because putting `onClick` on it clashes with the parent`s `onClick`.
 */
export function LemonButtonWithSideAction({
    sideAction,
    children,
    ...buttonProps
}: LemonButtonWithSideActionProps): JSX.Element {
    const { popup: sidePopup, ...sideActionRest } = sideAction
    const SideComponent = sidePopup ? LemonButtonWithPopup : LemonButton

    return (
        <div className="LemonButtonWithSideAction">
            {/* Bogus `sideIcon` div prevents overflow under the side button. */}
            <LemonButton {...buttonProps} sideIcon={<div />}>
                {children}
                {!buttonProps.fullWidth && <LemonSpacer vertical style={{ margin: '0 0 0 0.75rem' }} />}
            </LemonButton>
            <SideComponent
                className="side-button"
                popup={sidePopup as LemonButtonPopup}
                {...sideActionRest}
                type={buttonProps.type}
                translucent
            />
        </div>
    )
}

export interface LemonButtonWithPopupProps extends LemonButtonPropsBase {
    popup: LemonButtonPopup
    sideIcon?: React.ReactElement | null
}

/**
 * Styled button that opens a popup menu on click.
 * The difference vs. plain `LemonButton` is popup visibility being controlled internally, which is more convenient.
 */
export function LemonButtonWithPopup({
    popup: { onClickOutside, onClickInside, ...popupProps },
    onClick,
    ...buttonProps
}: LemonButtonWithPopupProps): JSX.Element {
    const parentPopupId = useContext(PopupContext)
    const [popupVisible, setPopupVisible] = useState(false)

    if (!buttonProps.children) {
        if (!buttonProps.icon) {
            buttonProps.icon = popupProps.placement?.startsWith('right') ? <IconChevronRight /> : <IconArrowDropDown />
        }
    } else if (!buttonProps.sideIcon) {
        buttonProps.sideIcon = popupProps.placement?.startsWith('right') ? <IconChevronRight /> : <IconArrowDropDown />
    }

    if (!('visible' in popupProps)) {
        popupProps.visible = popupVisible
    }

    return (
        <Popup
            onClickOutside={(e) => {
                setPopupVisible(false)
                onClickOutside?.(e)
            }}
            onClickInside={(e) => {
                setPopupVisible(false)
                onClickInside?.(e)
            }}
            {...popupProps}
        >
            <LemonButton
                onClick={(e) => {
                    setPopupVisible((state) => !state)
                    onClick?.(e)
                    if (parentPopupId !== 0) {
                        // If this button is inside another popup, let's not propagate this event so that
                        // the parent popup doesn't close
                        e.stopPropagation()
                    }
                }}
                active={popupProps.visible}
                {...buttonProps}
            />
        </Popup>
    )
}

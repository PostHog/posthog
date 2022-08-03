import clsx from 'clsx'
import React, { useContext, useState } from 'react'
import { IconArrowDropDown, IconChevronRight } from '../icons'
import { Link } from '../Link'
import { Popup, PopupProps, PopupContext } from '../Popup/Popup'
import { Spinner } from '../Spinner/Spinner'
import { Tooltip } from '../Tooltip'
import './LemonButton.scss'

export interface LemonButtonPopup extends Omit<PopupProps, 'children'> {
    closeOnClickInside?: boolean
}
export interface LemonButtonPropsBase extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
    children?: React.ReactNode
    type?: 'primary' | 'secondary' | 'tertiary' | 'stealth'
    status?: 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'primary-alt' | 'muted' | 'muted-alt'
    /** Whether hover style should be applied, signaling that the button is held active in some way. */
    active?: boolean
    /** URL to link to. */
    to?: string
    /** External URL to link to. */
    href?: string
    className?: string
    /** Whether the button should have a border */
    outlined?: boolean

    icon?: React.ReactElement | null
    sideIcon?: React.ReactElement | null
    loading?: boolean
    /** Tooltip to display on hover. */
    tooltip?: any
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    size?: 'small' | 'medium' | 'large'
    'data-attr'?: string
    'data-tooltip'?: string
}

export interface LemonButtonProps extends LemonButtonPropsBase {
    rightIcon?: React.ReactElement | null
}

/** Styled button. */
function LemonButtonInternal(
    {
        children,
        active = false,
        className,
        to,
        href,
        disabled,
        loading,
        outlined,
        type = 'tertiary',
        status = 'primary',
        icon,
        sideIcon,
        fullWidth,
        size,
        tooltip,
        ...buttonProps
    }: LemonButtonProps,
    ref: React.Ref<HTMLButtonElement>
): JSX.Element {
    // if (popup && (children2 || !buttonProps.icon) && !rowProps.sideIcon) {
    //     rowProps.sideIcon = <IconArrowDropDown />
    // }

    if (loading) {
        icon = <Spinner size="sm" />
    }
    let workingButton = (
        <button
            ref={ref}
            className={clsx(
                'LemonButton',
                `LemonButton--${type}`,
                `LemonButton--status-${status}`,
                !children && !!icon && `LemonButton--icon-only`,
                size && `LemonButton--${size}`,
                disabled && 'LemonButton--disabled',
                active && 'LemonButton--active',
                outlined && 'LemonButton--outlined',
                fullWidth && 'LemonButton--full-width',
                className
            )}
            disabled={disabled || loading}
            {...buttonProps}
        >
            {icon}
            {children ? <span className="flex items-center grow">{children}</span> : null}
            {sideIcon}
        </button>
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

    if (tooltip) {
        workingButton = <Tooltip title={tooltip}>{workingButton}</Tooltip>
    }

    return workingButton
}

export const LemonButton = React.forwardRef(LemonButtonInternal)

export type SideAction = Pick<
    LemonButtonProps,
    'onClick' | 'to' | 'disabled' | 'icon' | 'type' | 'tooltip' | 'data-attr'
> & {
    popup?: LemonButtonPopup
}

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
            <LemonButton
                {...buttonProps}
                sideIcon={!buttonProps.fullWidth ? <span className="LemonButtonWithSideAction--divider" /> : undefined}
            >
                {children}
            </LemonButton>
            <div className="LemonButtonWithSideAction--side-button">
                <SideComponent
                    // We don't want secondary style as it creates double borders
                    type={buttonProps.type !== 'secondary' ? buttonProps.type : undefined}
                    status={buttonProps.status}
                    popup={sidePopup as LemonButtonPopup}
                    {...sideActionRest}
                />
            </div>
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
    popup: { onClickOutside, onClickInside, closeOnClickInside = true, className: popupClassName, ...popupProps },
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
            className={popupClassName}
            onClickOutside={(e) => {
                setPopupVisible(false)
                onClickOutside?.(e)
            }}
            onClickInside={(e) => {
                e.stopPropagation()
                closeOnClickInside && setPopupVisible(false)
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

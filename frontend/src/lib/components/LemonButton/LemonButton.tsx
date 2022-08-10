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
export interface LemonButtonPropsBase
    // NOTE: We explicitly pick rather than omit to ensure thes components aren't used incorrectly
    extends Pick<React.ButtonHTMLAttributes<HTMLElement>, 'title' | 'onClick' | 'id' | 'tabIndex' | 'form'> {
    children?: React.ReactNode
    type?: 'primary' | 'secondary' | 'tertiary'
    status?: 'primary' | 'success' | 'warning' | 'danger' | 'primary-alt' | 'muted' | 'muted-alt' | 'stealth'
    /** Whether hover style should be applied, signaling that the button is held active in some way. */
    active?: boolean
    /** URL to link to. */
    to?: string
    /** External URL to link to. */
    href?: string
    className?: string

    icon?: React.ReactElement | null
    sideIcon?: React.ReactElement | null
    htmlType?: 'button' | 'submit' | 'reset'
    loading?: boolean
    /** Tooltip to display on hover. */
    tooltip?: any
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    center?: boolean
    /** @deprecated Buttons should never be disabled. Work with Design to find an alternative approach. */
    disabled?: boolean
    /** Special case value for buttons such as compact icon-only buttons */
    noPadding?: boolean
    size?: 'small' | 'medium' | 'large'
    'data-attr'?: string
    'data-tooltip'?: string
    'aria-label'?: string
}

export interface LemonButtonProps extends LemonButtonPropsBase {
    sideIcon?: React.ReactElement | null
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
        type = 'tertiary',
        status = 'primary',
        icon,
        sideIcon,
        fullWidth,
        center,
        size,
        tooltip,
        htmlType = 'button',
        noPadding,
        ...buttonProps
    }: LemonButtonProps,
    ref: React.Ref<HTMLElement>
): JSX.Element {
    if (loading) {
        icon = <Spinner size="sm" />
    }

    const ButtonComponent = to || href ? Link : 'button'

    if (ButtonComponent === 'button' && !buttonProps['aria-label'] && typeof tooltip === 'string') {
        buttonProps['aria-label'] = tooltip
    }

    let workingButton = (
        <ButtonComponent
            type={htmlType}
            ref={ref as any}
            className={clsx(
                'LemonButton',
                `LemonButton--${type}`,
                `LemonButton--status-${status}`,
                noPadding && `LemonButton--noPadding`,
                size && `LemonButton--${size}`,
                disabled && 'LemonButton--disabled',
                active && 'LemonButton--active',
                fullWidth && 'LemonButton--full-width',
                center && 'LemonButton--centered',
                !children && 'LemonButton--no-content',
                !!icon && `LemonButton--hasIcon`,
                !!sideIcon && `LemonButton--hasSideIcon`,
                className
            )}
            disabled={disabled || loading}
            to={to}
            href={href}
            target={href ? '_blank' : undefined}
            rel={href ? 'noopener noreferrer' : undefined}
            {...buttonProps}
        >
            {icon}
            {children ? <span className="LemonButton__content flex items-center">{children}</span> : null}
            {sideIcon}
        </ButtonComponent>
    )

    if (tooltip) {
        workingButton = <Tooltip title={tooltip}>{workingButton}</Tooltip>
    }

    return workingButton
}

export const LemonButton = React.forwardRef(LemonButtonInternal)

export type SideAction = Pick<
    LemonButtonProps,
    'onClick' | 'to' | 'disabled' | 'icon' | 'type' | 'tooltip' | 'data-attr' | 'aria-label'
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
                sideIcon={
                    <span
                        className={clsx(
                            'LemonButtonWithSideAction__spacer',
                            !buttonProps.fullWidth && 'LemonButtonWithSideAction__spacer--divider'
                        )}
                    />
                }
            >
                {children}
            </LemonButton>
            <div className="LemonButtonWithSideAction--side-button">
                <SideComponent
                    // We don't want secondary style as it creates double borders
                    type={buttonProps.type !== 'secondary' ? buttonProps.type : undefined}
                    status={buttonProps.status}
                    active={buttonProps.active}
                    popup={sidePopup as LemonButtonPopup}
                    noPadding
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
    className,
    ...buttonProps
}: LemonButtonWithPopupProps): JSX.Element {
    const parentPopupId = useContext(PopupContext)
    const [popupVisible, setPopupVisible] = useState(false)

    if (!buttonProps.children) {
        if (!buttonProps.icon) {
            buttonProps.icon = popupProps.placement?.startsWith('right') ? <IconChevronRight /> : <IconArrowDropDown />
        }
    } else if (buttonProps.sideIcon === undefined) {
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
                className={clsx('LemonButtonWithPopup', className)}
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

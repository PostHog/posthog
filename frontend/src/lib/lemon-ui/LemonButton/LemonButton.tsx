import clsx from 'clsx'
import React, { useContext } from 'react'
import { IconArrowDropDown, IconChevronRight } from 'lib/lemon-ui/icons'
import { Link } from '../Link'
import { Spinner } from '../Spinner/Spinner'
import { Tooltip, TooltipProps } from '../Tooltip'
import './LemonButton.scss'
import './LemonButtonLegacy.scss'
import './LemonButton3000.scss'
import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { PopoverReferenceContext } from '../Popover'

export type LemonButtonDropdown = Omit<LemonDropdownProps, 'children'>

export interface LemonButtonPropsBase
    // NOTE: We explicitly pick rather than omit to ensure these components aren't used incorrectly
    extends Pick<
        React.ButtonHTMLAttributes<HTMLElement>,
        | 'title'
        | 'onClick'
        | 'id'
        | 'tabIndex'
        | 'form'
        | 'onMouseDown'
        | 'onMouseEnter'
        | 'onMouseLeave'
        | 'onKeyDown'
        | 'role'
        | 'aria-haspopup'
    > {
    children?: React.ReactNode
    type?: 'primary' | 'secondary' | 'tertiary'
    /** Button color scheme. */
    status?: 'primary' | 'danger' | 'primary-alt' | 'muted' | 'stealth'
    /** Whether hover style should be applied, signaling that the button is held active in some way. */
    active?: boolean
    /** URL to link to. */
    to?: string
    /** force the "to" link to reload the page */
    disableClientSideRouting?: boolean
    /** If set clicking this button will open the page in a new tab. */
    targetBlank?: boolean
    /** External URL to link to. */
    className?: string

    /** Icon displayed on the left. */
    icon?: React.ReactElement | null
    /**
     * Icon displayed on the right.
     * If the button opens a dropdown, this icon will be a dropdown arrow by default. Set `sideIcon={null}` to disable.
     */
    sideIcon?: React.ReactElement | null
    htmlType?: 'button' | 'submit' | 'reset'
    loading?: boolean
    /** Tooltip to display on hover. */
    tooltip?: TooltipProps['title']
    tooltipPlacement?: TooltipProps['placement']
    /** Tooltip's `getPopupContainer`. **/
    getTooltipPopupContainer?: () => HTMLElement
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    center?: boolean
    /** @deprecated Buttons should never be quietly disabled. Use `disabledReason` to provide an explanation instead. */
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    noPadding?: boolean
    /** Hides the button chrome until hover. */
    stealth?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    'data-attr'?: string
    'aria-label'?: string
}

export interface LemonButtonProps extends LemonButtonPropsBase {
    sideIcon?: React.ReactElement | null
}

/** Styled button. */
export const LemonButton: React.FunctionComponent<LemonButtonProps & React.RefAttributes<HTMLButtonElement>> =
    React.forwardRef(
        (
            {
                children,
                active = false,
                className,
                disabled,
                disabledReason,
                loading,
                type = 'tertiary',
                status = 'primary',
                icon,
                sideIcon,
                fullWidth,
                center,
                size,
                tooltip,
                tooltipPlacement,
                stealth = false,
                htmlType = 'button',
                noPadding,
                to,
                targetBlank,
                disableClientSideRouting,
                getTooltipPopupContainer,
                onClick,
                ...buttonProps
            },
            ref
        ): JSX.Element => {
            const [popoverVisibility, popoverPlacement] = useContext(PopoverReferenceContext) || [false, null]

            if (!active && popoverVisibility) {
                active = true
            }

            if (popoverPlacement) {
                if (!children) {
                    if (icon === undefined) {
                        icon = popoverPlacement.startsWith('right') ? <IconChevronRight /> : <IconArrowDropDown />
                    }
                } else if (sideIcon === undefined) {
                    sideIcon = popoverPlacement.startsWith('right') ? <IconChevronRight /> : <IconArrowDropDown />
                }
            }
            if (loading) {
                icon = <Spinner textColored />
                disabled = true // Cannot interact with a loading button
            }

            let tooltipContent: TooltipProps['title']
            if (disabledReason) {
                disabled = true // Support `disabledReason` while maintaining compatibility with `disabled`
                if (tooltipContent) {
                    tooltipContent = (
                        <>
                            {tooltip}
                            <div className="mt-1 italic">{disabledReason}</div>
                        </>
                    )
                } else {
                    tooltipContent = <span className="italic">{disabledReason}</span>
                }
            } else {
                tooltipContent = tooltip
            }

            const ButtonComponent = to ? Link : 'button'
            const linkDependentProps = to
                ? {
                      disableClientSideRouting,
                      target: targetBlank ? '_blank' : undefined,
                      to: !disabled ? to : undefined,
                  }
                : { type: htmlType }

            if (ButtonComponent === 'button' && !buttonProps['aria-label'] && typeof tooltip === 'string') {
                buttonProps['aria-label'] = tooltip
            }

            let workingButton = (
                <ButtonComponent
                    ref={ref as any}
                    className={clsx(
                        'LemonButton',
                        `LemonButton--${type}`,
                        `LemonButton--status-${status}`,
                        loading && `LemonButton--loading`,
                        noPadding && `LemonButton--no-padding`,
                        size && `LemonButton--${size}`,
                        active && 'LemonButton--active',
                        fullWidth && 'LemonButton--full-width',
                        center && 'LemonButton--centered',
                        !children && 'LemonButton--no-content',
                        !!icon && `LemonButton--has-icon`,
                        !!sideIcon && `LemonButton--has-side-icon`,
                        stealth && 'LemonButton--is-stealth',
                        className
                    )}
                    onClick={!disabled ? onClick : undefined}
                    // We are using the ARIA disabled instead of native HTML because of this:
                    // https://css-tricks.com/making-disabled-buttons-more-inclusive/
                    aria-disabled={disabled}
                    {...linkDependentProps}
                    {...buttonProps}
                >
                    <span>
                        {icon ? <span className="LemonButton__icon">{icon}</span> : null}
                        {children ? <span className="LemonButton__content">{children}</span> : null}
                        {sideIcon ? <span className="LemonButton__icon">{sideIcon}</span> : null}
                    </span>
                </ButtonComponent>
            )

            if (tooltipContent) {
                workingButton = (
                    <Tooltip
                        title={tooltipContent}
                        placement={tooltipPlacement}
                        getPopupContainer={getTooltipPopupContainer}
                    >
                        {/* If the button is a `button` element and disabled, wrap it in a div so that the tooltip works */}
                        {disabled && ButtonComponent === 'button' ? <div>{workingButton}</div> : workingButton}
                    </Tooltip>
                )
            }

            return workingButton
        }
    )
LemonButton.displayName = 'LemonButton'

export type SideAction = Pick<
    LemonButtonProps,
    'onClick' | 'to' | 'disabled' | 'icon' | 'type' | 'tooltip' | 'data-attr' | 'aria-label' | 'status' | 'targetBlank'
> & {
    dropdown?: LemonButtonDropdown
    /**
     * Whether to show a divider between button contents and side action.
     * @default true // for non-full-width buttons
     * @default false // for full-width buttons
     */
    divider?: boolean
}

/** A LemonButtonWithSideAction can't have a sideIcon - instead it has a clickable sideAction. */
export interface LemonButtonWithSideActionProps extends LemonButtonPropsBase {
    sideAction: SideAction
}

/**
 * Styled button with a side action on the right.
 * We can't use `LemonRow`'s `sideIcon` prop because putting `onClick` on it clashes with the parent`s `onClick`.
 */
export const LemonButtonWithSideAction: React.FunctionComponent<
    LemonButtonWithSideActionProps & React.RefAttributes<HTMLButtonElement>
> = React.forwardRef(({ sideAction, children, ...buttonProps }, ref) => {
    const { dropdown: sideDropdown, divider = !buttonProps.fullWidth, ...sideActionRest } = sideAction
    const SideComponent = sideDropdown ? LemonButtonWithDropdown : LemonButton

    return (
        <div className={clsx('LemonButtonWithSideAction', `LemonButtonWithSideAction--${buttonProps.size}`)}>
            {/* Bogus `sideIcon` div prevents overflow under the side button. */}
            <LemonButton
                ref={ref}
                {...buttonProps}
                sideIcon={
                    <span
                        className={clsx(
                            'LemonButtonWithSideAction__spacer',
                            divider && 'LemonButtonWithSideAction__spacer--divider'
                        )}
                    />
                }
            >
                {children}
            </LemonButton>
            <div className="LemonButtonWithSideAction__side-button">
                <SideComponent
                    // We don't want secondary style as it creates double borders
                    type={buttonProps.type !== 'secondary' ? buttonProps.type : undefined}
                    status={buttonProps.status}
                    dropdown={sideDropdown as LemonButtonDropdown}
                    noPadding
                    {...sideActionRest}
                />
            </div>
        </div>
    )
})
LemonButtonWithSideAction.displayName = 'LemonButtonWithSideAction'

export interface LemonButtonWithDropdownProps extends LemonButtonPropsBase {
    dropdown: LemonButtonDropdown
    sideIcon?: React.ReactElement | null
}

/**
 * Styled button that opens a dropdown menu on click.
 * The difference vs. plain `LemonButton` is dropdown visibility being controlled internally, which is more convenient.
 * @deprecated In almost all cases you should use the newer `LemonMenu` with a `LemonButton` child.
 */
export const LemonButtonWithDropdown: React.FunctionComponent<
    LemonButtonWithDropdownProps & React.RefAttributes<HTMLButtonElement>
> = React.forwardRef(({ dropdown: dropdownProps, ...buttonProps }, ref): JSX.Element => {
    return (
        <LemonDropdown {...dropdownProps}>
            <LemonButton ref={ref} {...buttonProps} />
        </LemonDropdown>
    )
})
LemonButtonWithDropdown.displayName = 'LemonButtonWithDropdown'

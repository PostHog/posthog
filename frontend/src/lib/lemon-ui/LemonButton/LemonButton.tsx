import './LemonButton.scss'

import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import React, { useContext } from 'react'

import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { Link } from '../Link'
import { PopoverOverlayContext, PopoverReferenceContext } from '../Popover'
import { Spinner } from '../Spinner/Spinner'
import { Tooltip, TooltipProps } from '../Tooltip'

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
    status?: 'default' | 'alt' | 'danger'
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
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    center?: boolean
    /** @deprecated Buttons should never be quietly disabled. Use `disabledReason` to provide an explanation instead. */
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    /** Class for the wrapping div when the button is disabled */
    disabledReasonWrapperClass?: string
    noPadding?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    'data-attr'?: string
    'aria-label'?: string
    /** Whether to truncate the button's text if necessary */
    truncate?: boolean
}

export type SideAction = Pick<
    LemonButtonProps,
    | 'onClick'
    | 'to'
    | 'disableClientSideRouting'
    | 'disabled'
    | 'icon'
    | 'type'
    | 'tooltip'
    | 'tooltipPlacement'
    | 'data-attr'
    | 'aria-label'
    | 'status'
    | 'targetBlank'
> & {
    dropdown?: LemonButtonDropdown
    /**
     * Whether to show a divider between button contents and side action.
     * @default true // for non-full-width buttons
     * @default false // for full-width buttons
     */
    divider?: boolean
}

export interface LemonButtonWithoutSideActionProps extends LemonButtonPropsBase {
    sideIcon?: React.ReactElement | null
    sideAction?: null
}
/** A LemonButtonWithSideAction can't have a sideIcon - instead it has a clickable sideAction. */
export interface LemonButtonWithSideActionProps extends LemonButtonPropsBase {
    sideAction: SideAction
    sideIcon?: null
}
export type LemonButtonProps = LemonButtonWithoutSideActionProps | LemonButtonWithSideActionProps

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
                disabledReasonWrapperClass,
                loading,
                type = 'tertiary',
                status = 'default',
                icon,
                sideIcon,
                sideAction,
                fullWidth,
                center,
                size,
                tooltip,
                tooltipPlacement,
                htmlType = 'button',
                noPadding,
                to,
                targetBlank,
                disableClientSideRouting,
                onClick,
                truncate = false,
                ...buttonProps
            },
            ref
        ): JSX.Element => {
            const [popoverVisibility, popoverPlacement] = useContext(PopoverReferenceContext) || [false, null]
            const [, parentPopoverLevel] = useContext(PopoverOverlayContext)
            const within3000PageHeader = useContext(WithinPageHeaderContext)

            if (!active && popoverVisibility) {
                active = true
            }

            const usingSideActionDivider = sideAction && (sideAction.divider ?? !fullWidth)
            if (sideAction) {
                // Bogus `sideIcon` div prevents overflow under the side button.
                sideIcon = (
                    <span
                        className={clsx(
                            'LemonButtonWithSideAction__spacer',
                            usingSideActionDivider && 'LemonButtonWithSideAction__spacer--divider'
                        )}
                    />
                )
            } else if (popoverPlacement) {
                if (!children) {
                    if (icon === undefined) {
                        icon = popoverPlacement.startsWith('right') ? <IconChevronRight /> : <IconChevronDown />
                    }
                } else if (sideIcon === undefined) {
                    sideIcon = popoverPlacement.startsWith('right') ? <IconChevronRight /> : <IconChevronDown />
                }
            }
            if (loading) {
                icon = <Spinner textColored />
                disabled = true // Cannot interact with a loading button
            }
            if (within3000PageHeader && parentPopoverLevel === -1) {
                size = 'small' // Ensure that buttons in the page header are small (but NOT inside dropdowns!)
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
                        truncate && 'LemonButton--truncate',
                        className
                    )}
                    onClick={!disabled ? onClick : undefined}
                    // We are using the ARIA disabled instead of native HTML because of this:
                    // https://css-tricks.com/making-disabled-buttons-more-inclusive/
                    aria-disabled={disabled}
                    {...linkDependentProps}
                    {...buttonProps}
                >
                    <span className="LemonButton__chrome">
                        {icon ? <span className="LemonButton__icon">{icon}</span> : null}
                        {children ? <span className="LemonButton__content">{children}</span> : null}
                        {sideIcon ? <span className="LemonButton__icon">{sideIcon}</span> : null}
                    </span>
                </ButtonComponent>
            )

            if (tooltipContent) {
                workingButton = (
                    <Tooltip title={tooltipContent} placement={tooltipPlacement}>
                        {/* If the button is a `button` element and disabled, wrap it in a div so that the tooltip works */}
                        {disabled && ButtonComponent === 'button' ? (
                            <div className={clsx(disabledReasonWrapperClass)}>{workingButton}</div>
                        ) : (
                            workingButton
                        )}
                    </Tooltip>
                )
            }

            if (sideAction) {
                const { dropdown: sideDropdown, divider: _, ...sideActionRest } = sideAction
                const SideComponent = sideDropdown ? LemonButtonWithDropdown : LemonButton

                workingButton = (
                    <div
                        className={clsx(
                            'LemonButtonWithSideAction',
                            fullWidth && 'LemonButtonWithSideAction--full-width'
                        )}
                    >
                        {workingButton}
                        <div className="LemonButtonWithSideAction__side-button">
                            <SideComponent
                                type={type}
                                size={size}
                                status={status}
                                dropdown={sideDropdown as LemonButtonDropdown}
                                noPadding
                                active={active}
                                {...sideActionRest}
                            />
                        </div>
                    </div>
                )
            }

            return workingButton
        }
    )
LemonButton.displayName = 'LemonButton'

export const WithinPageHeaderContext = React.createContext<boolean>(false)

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

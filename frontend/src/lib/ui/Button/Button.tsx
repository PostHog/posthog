import { Link } from '@posthog/lemon-ui'
import { cva, VariantProps } from 'class-variance-authority'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/styles'
import { forwardRef } from 'react'

import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '../Dropdown/Dropdown'

export const buttonStyles = cva(
    `
        element-button 
        pt-[4.5px] pb-[5.5px] 
        text-left 
        items-center justify-center
        cursor-pointer
    `,
    {
        variants: {
            intent: {
                primary: [
                    'element-button-primary',
                    // 'element-has-elevation',
                    // 'element-has-elevation-primary',
                    // 'pb-[8.5px]',
                ],
                outline: ['element-button-outline'],
                muted: ['element-button-muted'],
                'muted-darker': ['element-button-muted-darker'],
                'top-bar-tabs': ['element-button-top-bar-tabs'],
            },
            active: {
                true: ['element-button-active'],
                false: [''],
            },
            size: {
                xs: ['element-button-size-xs', 'text-xs', 'px-2'],
                sm: ['element-button-size-sm', 'text-sm', 'px-2'],
                base: ['element-button-size-base', 'text-sm', 'px-3'],
                lg: ['element-button-size-lg', 'text-base', 'px-3'],
            },
            // This is only for styling purposes and is omitted from the props
            hasIcon: {
                true: ['gap-2'],
                false: [''],
            },
            // This is only for styling purposes and is omitted from the props
            hasIconLeft: {
                true: [''],
                false: [''],
            },
            // This is only for styling purposes and is omitted from the props
            hasIconRight: {
                true: [''],
                false: [''],
            },
            iconOnly: {
                true: [''],
                false: [''],
            },
            // This is only for styling purposes and is omitted from the props
            disabled: {
                true: ['cursor-not-allowed', 'opacity-50'],
                false: [''],
            },
            insideInput: {
                true: ['element-button-inside-input'],
                false: [''],
            },
            hasSideAction: {
                true: ['element-button-has-side-action'],
                false: [''],
            },
        },
        defaultVariants: {
            active: false,
            intent: 'muted',
            size: 'base',
        },
        compoundVariants: [
            {
                size: ['xs', 'sm'],
                hasIcon: true,
                className: 'px-2',
            },
            {
                size: ['base', 'lg'],
                hasIcon: true,
                className: 'px-2',
            },
            {
                hasIconLeft: true,
                hasIcon: true,
                className: 'element-button-has-icon-left',
            },
            {
                hasIconRight: true,
                hasIcon: true,
                className: 'element-button-has-icon-right',
            },
            {
                hasIconLeft: true,
                hasIconRight: true,
                className: 'element-button-has-icon-left-and-right',
            },
            {
                iconOnly: true,
                className: 'element-button-has-icon-only py-2',
            },
            {
                iconOnly: true,
                size: ['xs', 'sm'],
                className: 'py-2',
            },
            {
                iconOnly: true,
                size: ['base', 'lg'],
                className: 'py-3',
            },
            {
                intent: 'top-bar-tabs',
                className: 'pt-[7px] pb-[11px]',
            },
        ],
    }
)

export type ButtonSideAction = {
    icon?: React.ReactNode
    to?: string
    onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
}

export type ButtonVariantProps = Omit<
    VariantProps<typeof buttonStyles>,
    'disabled' | 'hasIcon' | 'hasIconLeft' | 'hasIconRight'
> & {
    children: React.ReactNode
    className?: string
    to?: string
    targetBlank?: boolean
    type?: 'button' | 'submit' | 'reset'
    // disabled?: boolean
    disableClientSideRouting?: boolean
    tooltip?: TooltipProps['title']
    tooltipPlacement?: TooltipProps['placement']
    disabledReason?: string | null | false
    iconOnly?: boolean
    iconRight?: React.ReactNode
    iconLeft?: React.ReactNode
    onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
    insideInput?: boolean
    dropdownContent?: React.ReactElement<typeof DropdownMenuContent>

    //TODO: on surface prop (so we can style the button based on the surface it sits on)

    sideAction?: Omit<ButtonVariantProps, 'intent' | 'insideInput' | 'hasSideAction'>
}

export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonVariantProps>(
    (
        {
            intent,
            className,
            to,
            targetBlank,
            type,
            disabledReason,
            disableClientSideRouting,
            tooltip,
            tooltipPlacement,
            iconRight,
            iconLeft,
            children,
            iconOnly,
            onClick,
            insideInput,
            sideAction,
            dropdownContent,
            ...rest
        },
        ref
    ) => {
        const ButtonComponent = to ? Link : dropdownContent ? DropdownMenuTrigger : 'button'
        let disabled = disabledReason ? true : false

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

        const linkDependentProps = to
            ? {
                  disableClientSideRouting,
                  target: targetBlank ? '_blank' : undefined,
                  to: !disabled ? to : undefined,
                  insideButton: true,
                  isButton: true,
                  // className: buttonStyles({
                  //     intent,
                  //     iconOnly,
                  // }),
              }
            : { type: type }

        let workingButton = (
            <ButtonComponent
                ref={ref as any}
                className={cn(
                    buttonStyles({
                        intent,
                        hasIcon: Boolean(iconLeft || iconRight),
                        hasIconLeft: Boolean(iconLeft),
                        hasIconRight: Boolean(iconRight),
                        iconOnly,
                        disabled,
                        insideInput,
                        hasSideAction: sideAction ? true : false,
                        ...rest,
                    }),
                    className
                )}
                disabled={disabled}
                onClick={(e) => {
                    onClick?.(e as React.MouseEvent<HTMLButtonElement>)
                }}
                {...linkDependentProps}
                {...rest}
            >
                {iconLeft && (
                    <span className={cn('element-button-icon', insideInput && 'element-button-icon-inside-input')}>
                        {iconLeft}
                    </span>
                )}
                {iconOnly ? (
                    <span className={cn('element-button-icon', insideInput && 'element-button-icon-inside-input')}>
                        {children}
                    </span>
                ) : (
                    <span className="flex-1 flex justify-between items-center gap-2">{children}</span>
                )}
                {iconRight && (
                    <span className={cn('element-button-icon', insideInput && 'element-button-icon-inside-input')}>
                        {iconRight}
                    </span>
                )}
            </ButtonComponent>
        )

        if (tooltipContent) {
            workingButton = (
                <Tooltip title={tooltipContent} placement={tooltipPlacement}>
                    {workingButton}
                </Tooltip>
            )
        }

        if (dropdownContent) {
            workingButton = (
                <DropdownMenu>
                    {workingButton}
                    {dropdownContent}
                </DropdownMenu>
            )
        }

        if (sideAction) {
            workingButton = (
                <div className="element-button-side-action-container">
                    {workingButton}
                    <Button
                        className={cn(
                            buttonStyles({
                                intent: 'muted',
                                iconOnly,
                                size: 'xs',
                            }),
                            'element-button-is-side-action'
                        )}
                        // intent="muted"
                        iconOnly
                        size="xs"
                        {...sideAction}
                    />
                </div>
            )
        }

        return workingButton
    }
)

Button.displayName = 'Button'

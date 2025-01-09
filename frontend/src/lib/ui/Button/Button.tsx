import { cva, VariantProps } from 'class-variance-authority'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/styles'
import { forwardRef } from 'react'

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
                primary: ['element-button-primary'],
                outline: ['element-button-outline'],
                muted: ['element-button-muted'],
                'muted-darker': ['element-button-muted-darker'],
            },
            active: {
                true: [''],
                false: [''],
            },
            size: {
                xs: ['element-button-size-xs', 'text-xs', 'px-2'],
                sm: ['element-button-size-sm', 'text-sm', 'px-2'],
                base: ['element-button-size-base', 'text-sm', 'px-3'],
                lg: ['element-button-size-lg', 'text-base', 'px-3'],
            },
            hasIcon: {
                true: ['gap-2'],
                false: [''],
            },
            hasIconLeft: {
                true: [''],
                false: [''],
            },
            hasIconRight: {
                true: [''],
                false: [''],
            },
            hasTooltip: {
                true: ['items-center', 'gap-2'],
                false: [''],
            },
            iconOnly: {
                true: [''],
                false: [''],
            },
            disabled: {
                true: ['pointer-events-none'],
                false: [''],
            },
            insideInput: {
                true: ['element-button-inside-input'],
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
        ],
    }
)

export type ButtonVariantProps = VariantProps<typeof buttonStyles> & {
    children: React.ReactNode
    className?: string
    to?: string
    targetBlank?: boolean
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    disableClientSideRouting?: boolean
    tooltip?: TooltipProps['title']
    tooltipPlacement?: TooltipProps['placement']
    disabledReason?: string | null | false
    iconOnly?: boolean
    iconRight?: React.ReactNode
    iconLeft?: React.ReactNode
    onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
    insideInput?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonVariantProps>(
    (
        {
            intent,
            className,
            to,
            targetBlank,
            type,
            disabled,
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
            ...rest
        },
        ref
    ) => {
        const ButtonComponent = to ? Link : 'button'

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
              }
            : { type: type }

        let workingButton = (
            <ButtonComponent
                ref={ref}
                className={cn(
                    buttonStyles({
                        intent,
                        hasIconLeft: Boolean(iconLeft),
                        hasIconRight: Boolean(iconRight),
                        iconOnly,
                        disabled,
                        insideInput,
                        ...rest,
                    }),
                    className
                )}
                disabled={disabled}
                {...linkDependentProps}
                {...rest}
                onClick={(e) => {
                    onClick && onClick(e as React.MouseEvent<HTMLButtonElement>)
                }}
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

        return workingButton
    }
)

Button.displayName = 'Button'

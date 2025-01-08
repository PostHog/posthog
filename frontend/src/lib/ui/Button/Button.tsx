import { cva, VariantProps } from 'class-variance-authority'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/styles'
import { forwardRef } from 'react'

const button = cva(['element-button', 'pt-[4.5px]', 'pb-[5.5px]', 'grid', 'grid-cols-1', 'text-left', 'items-center'], {
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
            xs: ['text-xs', 'px-2', '[&_svg]:size-[14px]', 'min-h-[26px]'],
            sm: ['text-sm', 'px-2', '[&_svg]:size-[20px]', 'min-h-[30px]'],
            base: ['text-sm', 'px-3', '[&_svg]:size-[24px]', 'min-h-[34px]'],
            lg: ['text-base', 'px-3', '[&_svg]:size-[28px]', 'min-h-[46px]'],
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
            className: 'xs-or-sm-has-icon px-2',
        },
        {
            size: ['base', 'lg'],
            hasIcon: true,
            className: 'base-or-lg-has-icon px-2',
        },
        {
            hasIconLeft: true,
            hasIcon: true,
            className: 'grid grid-cols-[24px_1fr]',
        },
        {
            hasIconRight: true,
            hasIcon: true,
            className: 'grid grid-cols-[1fr_24px]',
        },
        {
            hasIconLeft: true,
            hasIconRight: true,
            className: 'grid grid-cols-[24px_1fr_24px]',
        },
    ],
})

export type ButtonVariantProps = VariantProps<typeof button> & {
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
    iconRight?: React.ReactNode
    iconLeft?: React.ReactNode
    onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
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
            onClick,
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
                    button({
                        intent,
                        hasIconLeft: Boolean(iconLeft),
                        hasIconRight: Boolean(iconRight),
                        ...rest,
                    }),
                    className
                )}
                {...linkDependentProps}
                {...rest}
                onClick={(e) => {
                    onClick && onClick(e as React.MouseEvent<HTMLButtonElement>)
                }}
            >
                {iconLeft && <span className="element-button-icon">{iconLeft}</span>}
                <span className="flex-1 flex justify-between items-center gap-2">{children}</span>
                {iconRight && <span className="element-button-icon">{iconRight}</span>}
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

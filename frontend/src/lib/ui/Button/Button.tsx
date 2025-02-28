import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from 'lib/utils/css-classes'
import * as React from 'react'

const buttonIconVariants = cva(
    `flex
    aspect-square
    items-center
    justify-center
    rounded-sm
    text-sm
    font-medium`,
    {
        variants: {
            size: {
                default: 'size-6',
            },
            isOnLeft: {
                true: '-ml-1',
                false: '',
            },
            isOnRight: {
                true: '-mr-1',
                false: '',
            },
        },
        defaultVariants: {
            size: 'default',
        },
    }
)

interface ButtonIconProps extends VariantProps<typeof buttonIconVariants> {
    className?: string
    icon: React.ReactNode
}

const ButtonIcon = React.forwardRef<HTMLSpanElement, ButtonIconProps>(({ className, ...props }, ref) => {
    return <span ref={ref} className={cn(buttonIconVariants({ className }))} {...props} />
})
ButtonIcon.displayName = 'ButtonIcon'

const buttonVariants = cva(
    `relative
    inline-flex
    w-fit
    items-center
    justify-start
    gap-[5px]
    cursor-pointer
    whitespace-nowrap
    rounded-sm
    text-sm
    font-medium
    transition-colors
    disabled:pointer-events-none
    disabled:opacity-50
    data-[disabled]:pointer-events-none
    data-[disabled]:opacity-50
    [&_svg]:pointer-events-none
    [&_svg]:size-4
    [&_svg]:shrink-0`,
    {
        variants: {
            variant: {
                default:
                    'bg-transparent text-primary hover:bg-fill-highlight-100 data-[highlighted]:bg-fill-highlight-100',
                'default-inverse':
                    'bg-transparent text-primary-inverse hover:bg-fill-highlight-inverse-100 data-[highlighted]:bg-fill-highlight-inverse-100',
                // destructive:
                //     "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
                // outline:
                //     "border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
                // secondary:
                //     "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
                // ghost: "hover:bg-accent hover:text-accent-foreground",
                // link: "text-primary underline-offset-4 hover:underline",
            },
            size: {
                default: 'h-[30px] px-[5px] py-[3px]',
                sm: 'h-7 rounded-md px-3 text-xs',
                lg: 'h-10 rounded-md px-8',
                icon: 'size-6',
            },
            active: {
                true: '',
                false: '',
            },
        },
        compoundVariants: [
            {
                variant: 'default',
                active: true,
                className: 'bg-fill-highlight-150',
            },
            {
                variant: 'default-inverse',
                active: true,
                className: 'bg-fill-highlight-inverse-150',
            },
        ],
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
    asChild?: boolean
    iconLeft?: ButtonIconProps
    iconRight?: ButtonIconProps
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant, size, active, asChild = false, iconLeft, iconRight, children, ...props }, ref) => {
        const Comp = asChild ? Slot : 'button'
        return (
            <Comp className={cn(buttonVariants({ variant, active, size, className }))} ref={ref} {...props}>
                {iconLeft && (
                    <span className={buttonIconVariants({ size: iconLeft.size, isOnLeft: true })}>{iconLeft.icon}</span>
                )}
                <span>{children}</span>
                {iconRight && (
                    <span className={buttonIconVariants({ size: iconRight.size, isOnRight: true })}>
                        {iconRight.icon}
                    </span>
                )}
            </Comp>
        )
    }
)
Button.displayName = 'Button'

export { Button, ButtonIcon, type ButtonIconProps, type ButtonProps, buttonVariants }

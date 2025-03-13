import { cva, VariantProps } from 'class-variance-authority'
import { cn } from 'lib/utils/css-classes'
import { forwardRef } from 'react'

const iconWrapperVariants = cva('flex place-items-center aspect-square', {
    variants: {
        size: {
            xs: 'size-3',
            sm: 'size-4',
            md: 'size-5',
            lg: 'size-6',
        },
        intent: {
            default: '',
            primary: 'text-primary',
            secondary: 'text-secondary',
            tertiary: 'text-tertiary',
        },
    },
    defaultVariants: {
        size: 'md',
        intent: 'default',
    },
})

export type IconWrapper = VariantProps<typeof iconWrapperVariants> & {
    className?: string
    innerClassName?: string
    children: React.ReactNode
}

export const IconWrapper = forwardRef<HTMLDivElement, IconWrapper>(
    ({ className, size = 'md', intent = 'default', children }, ref) => {
        return (
            <div className={cn(iconWrapperVariants({ size, intent }), className)} ref={ref}>
                {children}
            </div>
        )
    }
)

IconWrapper.displayName = 'IconWrapper'

import { cva, VariantProps } from 'class-variance-authority'
import { cn } from 'lib/utils/css-classes'
import { forwardRef } from 'react'

const iconVariants = cva('flex place-items-center aspect-square', {
    variants: {
        size: {
            xs: 'size-3',
            sm: 'size-4',
            md: 'size-5',
            lg: 'size-6',
        },
    },
})

export type NewIconProps = VariantProps<typeof iconVariants> & {
    className?: string
    innerClassName?: string
    children: React.ReactNode
}

export const Icon = forwardRef<HTMLDivElement, NewIconProps>(({ className, size = 'md', children }, ref) => {
    return (
        <div className={cn(iconVariants({ size }), className)} ref={ref}>
            {children}
        </div>
    )
})

Icon.displayName = 'Icon'

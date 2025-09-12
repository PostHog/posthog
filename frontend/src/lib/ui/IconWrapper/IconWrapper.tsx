import { type VariantProps, cva } from 'cva'
import { forwardRef } from 'react'

import { cn } from 'lib/utils/css-classes'

const iconWrapperVariants = cva({
    base: 'flex place-items-center aspect-square',
    variants: {
        size: {
            sm: 'size-4 [&_svg]:size-3',
            md: 'size-5 [&_svg]:size-4',
            lg: 'size-6 [&_svg]:size-5',
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
        intent: 'secondary',
    },
})

export type IconWrapperVariantProps = VariantProps<typeof iconWrapperVariants>

export interface IconWrapperProps extends IconWrapperVariantProps {
    className?: string
    children: React.ReactNode
    ref?: React.Ref<HTMLDivElement>
}

export const IconWrapper = forwardRef<HTMLDivElement, IconWrapperProps>(
    ({ className, size = 'md', intent = 'secondary', children }, ref) => {
        return (
            <div className={cn(iconWrapperVariants({ size, intent }), className)} ref={ref}>
                {children}
            </div>
        )
    }
)

IconWrapper.displayName = 'IconWrapper'

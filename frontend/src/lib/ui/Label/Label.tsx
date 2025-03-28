import { cva } from 'cva'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, HTMLAttributes } from 'react'

const labelVariants = cva({
    base: 'font-semibold',
    variants: {
        intent: {
            menu: 'text-tertiary uppercase font-semibold text-xs leading-6 tracking-[0.075em]',
        },
    },
})

interface LabelProps extends HTMLAttributes<HTMLDivElement> {
    intent?: 'menu'
}

export const Label = forwardRef<HTMLDivElement, LabelProps>(({ className, intent, ...props }, ref) => {
    return <div className={cn(labelVariants({ intent }), className)} {...props} ref={ref} />
})

Label.displayName = 'Label'

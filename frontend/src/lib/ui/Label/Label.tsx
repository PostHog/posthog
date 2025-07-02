import { cva } from 'cva'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, LabelHTMLAttributes } from 'react'

const labelVariants = cva({
    base: 'font-semibold',
    variants: {
        intent: {
            menu: 'text-tertiary uppercase font-semibold text-[0.6875rem] leading-5 tracking-[0.075em] pt-1',
        },
    },
})

interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
    intent?: 'menu'
}

export const Label = forwardRef<HTMLLabelElement, LabelProps>(({ className, intent, ...props }, ref) => {
    return <label className={cn(labelVariants({ intent }), className)} {...props} ref={ref} />
})

Label.displayName = 'Label'

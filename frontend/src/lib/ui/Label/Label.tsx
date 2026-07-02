import { cva } from 'cva'
import { HTMLAttributes, LabelHTMLAttributes, forwardRef } from 'react'

import { cn } from 'lib/utils/css-classes'

const labelVariants = cva({
    base: 'font-semibold',
    variants: {
        intent: {
            menu: 'text-tertiary uppercase font-semibold text-[0.6875rem] leading-5 tracking-[0.075em]',
        },
    },
})

export interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
    intent?: 'menu'
}

export const Label = forwardRef<HTMLLabelElement, LabelProps>(({ className, intent, htmlFor, ...props }, ref) => {
    if (!htmlFor) {
        // Without an associated control this renders as a static <div>. A menu-styled caption here
        // is inert, so suppress the text cursor and text selection — otherwise it reads as a
        // clickable menu item and invites dead clicks. Interactive parents (e.g. a collapsible
        // trigger) re-enable cursor-pointer via className, which twMerge lets win.
        const { form, ...divProps } = props as LabelHTMLAttributes<HTMLLabelElement>
        return (
            <div
                className={cn(labelVariants({ intent }), intent === 'menu' && 'cursor-default select-none', className)}
                ref={ref as React.Ref<HTMLDivElement>}
                {...(divProps as HTMLAttributes<HTMLDivElement>)}
            />
        )
    }
    return <label className={cn(labelVariants({ intent }), className)} htmlFor={htmlFor} ref={ref} {...props} />
})

Label.displayName = 'Label'

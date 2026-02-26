import { cva } from 'cva'
import { HTMLAttributes, LabelHTMLAttributes } from 'react'

import { cn } from 'lib/utils/css-classes'

const labelVariants = cva({
    base: 'font-semibold',
    variants: {
        intent: {
            menu: 'text-tertiary uppercase font-semibold text-[0.6875rem] leading-5 tracking-[0.075em]',
        },
    },
})

interface LabelAsLabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
    intent?: 'menu'
    ref?: React.Ref<HTMLLabelElement>
}

export type LabelProps = LabelAsLabelProps

export const Label = ({ ref, className, intent, htmlFor, ...props }: LabelProps): JSX.Element => {
    if (!htmlFor) {
        return (
            <div
                className={cn(labelVariants({ intent }), className)}
                ref={ref as React.Ref<HTMLDivElement>}
                {...(props as HTMLAttributes<HTMLDivElement>)}
            />
        )
    }
    return <label className={cn(labelVariants({ intent }), className)} htmlFor={htmlFor} ref={ref} {...props} />
}

Label.displayName = 'Label'

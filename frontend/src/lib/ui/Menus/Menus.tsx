import { forwardRef } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

/* -------------------------------------------------------------------------- */
/*                           Menu Separator                                 */
/* -------------------------------------------------------------------------- */
export const MenuSeparator = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => {
        return <div ref={ref} className={cn('my-1 h-px bg-border-primary shrink-0 -mx-1', className)} {...props} />
    }
)
MenuSeparator.displayName = 'MenuSeparator'

/* -------------------------------------------------------------------------- */
/*                           Menu Open Indicator                             */
/* -------------------------------------------------------------------------- */
interface MenuOpenIndicatorProps extends React.HTMLAttributes<HTMLOrSVGElement> {
    intent?: 'default' | 'sub'
}
export const MenuOpenIndicator = ({ className, intent = 'default', ...props }: MenuOpenIndicatorProps): JSX.Element => {
    return (
        <IconChevronRight
            className={cn(
                'ml-auto size-3 text-secondary rotate-90 group-data-[state=open]/button-primitive:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none',
                intent === 'sub' && 'rotate-0 group-data-[state=open]/button-primitive:rotate-0',
                className
            )}
            {...props}
        />
    )
}
MenuOpenIndicator.displayName = 'MenuOpenIndicator'

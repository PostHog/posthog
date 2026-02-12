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
    direction?: 'up' | 'down' | 'left' | 'right'
}
export const MenuOpenIndicator = ({
    className,
    intent = 'default',
    direction = 'down',
    ...props
}: MenuOpenIndicatorProps): JSX.Element => {
    const computedDirection = intent === 'sub' || direction === 'right' ? 'right' : direction
    return (
        <IconChevronRight
            className={cn(
                'ml-auto size-3 text-secondary transition-transform duration-200 prefers-reduced-motion:transition-none',
                computedDirection === 'up' &&
                    '-rotate-90 group-data-[state=open]/button-primitive:rotate-90 group-data-[popup-open]/button-primitive:rotate-90',
                computedDirection === 'down' &&
                    'rotate-90 group-data-[state=open]/button-primitive:-rotate-90 group-data-[popup-open]/button-primitive:-rotate-90',
                computedDirection === 'left' &&
                    'rotate-180 group-data-[state=open]/button-primitive:rotate-0 group-data-[popup-open]/button-primitive:rotate-0',
                computedDirection === 'right' &&
                    'rotate-0 group-data-[state=open]/button-primitive:rotate-180 group-data-[popup-open]/button-primitive:rotate-180',
                className
            )}
            {...props}
        />
    )
}
MenuOpenIndicator.displayName = 'MenuOpenIndicator'

import clsx from 'clsx'
import { forwardRef, HTMLAttributes } from 'react'

interface IconWindowProps extends HTMLAttributes<HTMLDivElement> {
    value: number | string
    size?: 'small' | 'medium'
    className?: string
}

// forwardRef so this can be used as a Tooltip trigger — base-ui's Tooltip.Trigger
// merges its ref and pointer event handlers onto the rendered child, which only
// works if the child accepts a ref and spreads additional DOM props.
export const IconWindow = forwardRef<HTMLDivElement, IconWindowProps>(function IconWindow(
    { value, className = '', size = 'medium', ...rest },
    ref
): JSX.Element {
    const shortValue = typeof value === 'number' ? value : String(value).charAt(0)

    return (
        <div
            ref={ref}
            className={clsx(
                'flex justify-center items-center shrink-0 bg-muted-alt text-white rounded',
                size === 'medium' && 'w-5 h-5',
                size === 'small' && 'w-4 h-4',
                className
            )}
            {...rest}
        >
            <span
                className={clsx(
                    'font-bold select-none',
                    size === 'medium' && 'text-xs',
                    size === 'small' && 'text-xxs'
                )}
            >
                {shortValue}
            </span>
        </div>
    )
})

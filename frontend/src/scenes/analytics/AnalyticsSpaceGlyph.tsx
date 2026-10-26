import { cn } from '@posthog/quill'

import { analyticsSpaceColor } from './analyticsUtils'

/** A space's mark: a coloured tile with its initial, so each space reads the same wherever it is listed. */
export function AnalyticsSpaceGlyph({
    name,
    size = 'sm',
    className,
}: {
    name: string
    size?: 'sm' | 'md' | 'lg'
    className?: string
}): JSX.Element {
    return (
        <span
            aria-hidden
            className={cn(
                'inline-flex shrink-0 items-center justify-center rounded-md font-semibold text-white uppercase',
                size === 'sm' && 'size-4 rounded text-[9px]',
                size === 'md' && 'size-6 text-xs',
                size === 'lg' && 'size-10 rounded-lg text-base',
                className
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: analyticsSpaceColor(name) }}
        >
            {name.trim().charAt(0) || '#'}
        </span>
    )
}

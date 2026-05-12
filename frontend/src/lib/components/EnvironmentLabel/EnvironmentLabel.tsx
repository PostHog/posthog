import { cn } from 'lib/utils/css-classes'

import { EnvironmentLabelColor } from '~/types'

import { DEFAULT_ENVIRONMENT_LABEL_COLOR, ENVIRONMENT_LABEL_COLOR_BY_KEY } from './environmentLabels'

interface EnvironmentLabelProps {
    label: string | null | undefined
    color: EnvironmentLabelColor | null | undefined
    size?: 'xs' | 'sm'
    className?: string
}

/**
 * Compact colored pill used to surface which environment the user is in.
 * Renders nothing when the team has no label set, so callers don't need to guard.
 */
export function EnvironmentLabel({ label, color, size = 'sm', className }: EnvironmentLabelProps): JSX.Element | null {
    const trimmed = label?.trim()
    if (!trimmed) {
        return null
    }

    const palette = ENVIRONMENT_LABEL_COLOR_BY_KEY[color ?? DEFAULT_ENVIRONMENT_LABEL_COLOR]
    const sizeClasses = size === 'xs' ? 'text-xxs px-1 py-px' : 'text-xs px-1.5 py-0.5'

    return (
        <span
            className={cn(
                'inline-flex items-center rounded font-semibold leading-tight uppercase tracking-wide shrink-0',
                palette.pillClassName,
                sizeClasses,
                className
            )}
            // The label can be long; truncating in CSS lets the surrounding flex layout shrink it.
            title={trimmed}
        >
            <span className="truncate max-w-[120px]">{trimmed}</span>
        </span>
    )
}

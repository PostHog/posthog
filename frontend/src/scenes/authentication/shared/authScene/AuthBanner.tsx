import clsx from 'clsx'
import { type ReactNode } from 'react'

import { IconCheckCircle, IconWarning } from '@posthog/icons'

export type AuthBannerVariant = 'note' | 'warning' | 'danger' | 'success'

// Every variant keeps the dashed note's shape, so stacked banners read as part of the auth card. The
// scene remaps `text-warning` to the primary text color, so the warning accent reads `--warning`.
const VARIANT_CLASSES: Record<AuthBannerVariant, string> = {
    note: 'AuthScene__note text-secondary',
    warning: 'bg-[var(--auth-scene-note-bg)] border-[var(--warning)] text-primary',
    danger: 'bg-danger-highlight border-danger text-primary',
    success: 'bg-success-highlight border-success text-primary',
}

const VARIANT_ICONS: Partial<Record<AuthBannerVariant, ReactNode>> = {
    warning: <IconWarning className="text-[var(--warning)]" />,
    success: <IconCheckCircle className="text-success" />,
}

export function AuthBanner({
    variant,
    icon,
    className,
    children,
}: {
    variant: AuthBannerVariant
    /** Replaces the variant's own icon. */
    icon?: ReactNode
    className?: string
    children: ReactNode
}): JSX.Element {
    const shownIcon = icon ?? VARIANT_ICONS[variant]

    return (
        <div
            role={variant === 'danger' ? 'alert' : undefined}
            className={clsx(
                'flex gap-2.5 items-start py-3 px-3.5 text-sm leading-relaxed text-left border border-dashed rounded',
                VARIANT_CLASSES[variant],
                className
            )}
        >
            {shownIcon && (
                <span className="shrink-0 text-base leading-none mt-0.5" aria-hidden>
                    {shownIcon}
                </span>
            )}
            <div className="flex-1 min-w-0">{children}</div>
        </div>
    )
}

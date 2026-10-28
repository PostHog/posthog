import clsx from 'clsx'
import { type ReactNode } from 'react'

import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

export type AuthBannerVariant = 'note' | 'warning' | 'danger' | 'success'

// Every variant shares the note's surface, so banners read as part of the auth card. A solid outline
// mixed from the variant's color and the icon carry its meaning. The scene remaps `text-warning` to
// the primary text color, so the colors read the global `--warning`, `--danger` and `--success`.
const VARIANT_CLASSES: Record<AuthBannerVariant, string> = {
    note: 'border-[color:var(--auth-scene-note-border)] text-secondary',
    warning: 'border-[color:color-mix(in_srgb,var(--warning)_55%,transparent)] text-primary',
    danger: 'border-[color:color-mix(in_srgb,var(--danger)_55%,transparent)] text-primary',
    success: 'border-[color:color-mix(in_srgb,var(--success)_55%,transparent)] text-primary',
}

const VARIANT_ICONS: Partial<Record<AuthBannerVariant, ReactNode>> = {
    warning: <IconWarning className="text-[var(--warning)]" />,
    danger: <IconErrorOutline className="text-[var(--danger)]" />,
    success: <IconCheckCircle className="text-[var(--success)]" />,
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
                'flex gap-2.5 items-start py-3 px-3.5 text-sm leading-relaxed text-left rounded',
                'bg-[var(--auth-scene-note-bg)] border',
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

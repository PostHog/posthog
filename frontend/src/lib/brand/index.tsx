// The app-facing entry point for the PostHog logo. Always import from `lib/brand` — never
// `@posthog/brand/logo` directly. The raw package is presentation-only (its gradient wordmark
// is hard-coded `#111`, so it is neither theme- nor holiday-aware); this module is the single
// choke point that adapts it to dark mode and to the holiday season, so those behaviors can't
// drift per-consumer.
import { Logo as BrandLogo } from '@posthog/brand/logo'
import type { LogoProps, LogomarkProps } from '@posthog/brand/logo'

import { currentHoliday } from 'lib/holidays'
import { cn } from 'lib/utils/css-classes'

/**
 * Named logo sizes. Callers pick one of these instead of hand-tuning pixel dimensions per surface —
 * `md` is the standard logo (the landscape mark renders at the ubiquitous 160px width). A token sets
 * the rendered **height**; width always follows from the mark's aspect ratio, so call sites never
 * set width and height themselves. Omit `size` to fill the container (`width: 100%`, e.g. the toolbar).
 */
export type LogoSize = 'sm' | 'md' | 'lg'

const LOGO_SIZE_HEIGHTS: Record<LogoSize, number> = {
    sm: 24, // compact: watermarks, inline marks, small onboarding headers
    md: 28, // default: the standard logo — landscape renders at 160px wide (exporters, player, most)
    lg: 48, // hero: emphasis surfaces (coupon campaigns, splash screens)
}

// Package props are width-driven (`size`/`width` set width, height follows). We drive by height
// instead, so one token scales any layout consistently — hide the raw dimension props from callers.
type WithLogoSize<P> = Omit<P, 'size' | 'width' | 'height'> & { size?: LogoSize }
export type AppLogoProps = WithLogoSize<LogoProps>
export type AppLogomarkProps = WithLogoSize<LogomarkProps>

/**
 * The PostHog logo, adapted to the app's theme. With no explicit `variant` it renders the
 * gradient mark in light mode and a white mono mark in dark mode (the package gradient wordmark
 * is hard-coded dark, so it can't invert on its own). Pin a `variant` for always-light surfaces.
 */
export function Logo({ variant, className, size, ...props }: AppLogoProps): JSX.Element {
    const height = size ? LOGO_SIZE_HEIGHTS[size] : undefined
    if (variant) {
        return <BrandLogo variant={variant} height={height} className={className} {...props} />
    }
    return (
        <>
            <BrandLogo height={height} className={cn('dark:hidden', className)} {...props} />
            <BrandLogo
                variant="mono"
                color="white"
                height={height}
                className={cn('hidden dark:block', className)}
                {...props}
            />
        </>
    )
}

/**
 * The hedgehog logomark, theme-aware like {@link Logo}, and dressed for the current holiday
 * unless a `holiday` is passed explicitly (stories pass one to keep snapshots deterministic).
 * `size` sets the height (see {@link LogoSize}); `jumpOnClick` and other package props pass through.
 */
export function Logomark({ variant, className, holiday, size, ...props }: AppLogomarkProps): JSX.Element {
    const resolvedHoliday = holiday ?? currentHoliday()
    const height = size ? LOGO_SIZE_HEIGHTS[size] : undefined
    if (variant) {
        return (
            <BrandLogo.Logomark
                variant={variant}
                holiday={resolvedHoliday}
                height={height}
                className={className}
                {...props}
            />
        )
    }

    return (
        <>
            <BrandLogo.Logomark
                holiday={resolvedHoliday}
                height={height}
                className={cn('dark:hidden', className)}
                {...props}
            />
            <BrandLogo.Logomark
                variant="mono"
                color="white"
                holiday={resolvedHoliday}
                height={height}
                className={cn('hidden dark:block', className)}
                {...props}
            />
        </>
    )
}

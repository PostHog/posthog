import { cn } from 'lib/utils/css-classes'

import { PostHogLogoGradient } from './PostHogLogoGradient'
import { PostHogLogoWhite } from './PostHogLogoWhite'

export interface PostHogLogoProps {
    className?: string
    'aria-hidden'?: boolean | 'true' | 'false'
}

/**
 * Theme-adaptive PostHog logo (landscape lockup) — the default drop-in.
 *
 * Renders the gradient lockup in light mode and the solid-white lockup in dark mode, swapped
 * purely via CSS off the `[theme="dark"]` attribute PostHog sets on `<body>`. Both children are
 * byte-for-byte the source assets — nothing is recolored. For a fixed treatment, use the exact
 * variants directly (PostHogLogoGradient, PostHogLogoWhite, PostHogLogoColor, …).
 */
export function PostHogLogo({ className, 'aria-hidden': ariaHidden }: PostHogLogoProps): JSX.Element {
    return (
        <>
            <PostHogLogoGradient className={cn('dark:hidden', className)} aria-hidden={ariaHidden} />
            <PostHogLogoWhite className={cn('hidden dark:inline', className)} aria-hidden={ariaHidden} />
        </>
    )
}

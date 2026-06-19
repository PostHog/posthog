import { cn } from 'lib/utils/css-classes'

import { PostHogLogoGradientPortrait } from './PostHogLogoGradientPortrait'
import { PostHogLogoWhitePortrait } from './PostHogLogoWhitePortrait'

export interface PostHogLogoPortraitProps {
    className?: string
    'aria-hidden'?: boolean | 'true' | 'false'
}

/**
 * Theme-adaptive PostHog logo (portrait lockup) — icon stacked above the wordmark.
 *
 * Renders the gradient lockup in light mode and the solid-white lockup in dark mode, swapped
 * purely via CSS off the `[theme="dark"]` attribute PostHog sets on `<body>`. Both children are
 * byte-for-byte the source assets — nothing is recolored. For a fixed treatment, use the exact
 * variants directly (PostHogLogoGradientPortrait, PostHogLogoWhitePortrait, …).
 */
export function PostHogLogoPortrait({ className, 'aria-hidden': ariaHidden }: PostHogLogoPortraitProps): JSX.Element {
    return (
        <>
            <PostHogLogoGradientPortrait className={cn('dark:hidden', className)} aria-hidden={ariaHidden} />
            <PostHogLogoWhitePortrait className={cn('hidden dark:inline', className)} aria-hidden={ariaHidden} />
        </>
    )
}

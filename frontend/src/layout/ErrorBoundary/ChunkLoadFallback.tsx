import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { cn } from 'lib/utils/css-classes'

interface ChunkLoadFallbackProps {
    className?: string
}

/** Shown when a chunk is still missing after the automatic reload, so only the user can clear it. */
export function ChunkLoadFallback({ className }: ChunkLoadFallbackProps): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            className={cn('m-4', className)}
            action={{ children: 'Reload the page', onClick: () => window.location.reload() }}
        >
            PostHog was updated while this page was open, so part of it could not load. Reload the page to get the
            latest version.
        </LemonBanner>
    )
}

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { cn } from 'lib/utils/css-classes'

interface ChunkLoadFallbackProps {
    className?: string
}

/**
 * Shown when a chunk still fails to download after the automatic reload. The cause can be a deploy
 * that deleted the chunk, but also a network, proxy, or extension failure, and nothing in the error
 * tells them apart, so the copy names no cause and covers both recoveries.
 */
export function ChunkLoadFallback({ className }: ChunkLoadFallbackProps): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            className={cn('m-4', className)}
            action={{ children: 'Reload the page', onClick: () => window.location.reload() }}
        >
            Your browser could not download part of this page. Reload to try again. If it keeps happening, try a
            different network, or turn off browser extensions and proxies.
        </LemonBanner>
    )
}

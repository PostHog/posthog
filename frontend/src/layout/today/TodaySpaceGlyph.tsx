import { IconLock } from '@posthog/icons'
import { cn } from '@posthog/quill'

/** A lock for a space only some people can see, a `#` for the rest. */
export function TodaySpaceGlyph({ locked, className }: { locked: boolean; className?: string }): JSX.Element {
    return locked ? (
        <IconLock className={className} />
    ) : (
        <span aria-hidden className={cn('font-mono', className)}>
            #
        </span>
    )
}

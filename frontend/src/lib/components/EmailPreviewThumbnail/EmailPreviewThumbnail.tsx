import { cn } from 'lib/utils/css-classes'

// Email designs are laid out for a 600px canvas. Each size renders that canvas and scales it to its width,
// so the thumbnail shows the whole design and not its top-left corner. Scale is width / 600.
const SIZE_CLASSES = {
    chip: 'w-10 h-7 [--email-preview-scale:0.0667]',
    card: 'w-40 h-28 [--email-preview-scale:0.2667]',
} as const

export interface EmailPreviewThumbnailProps {
    /** Self-contained email html. Rendered in a fully sandboxed iframe: no scripts, no same-origin access. */
    html: string
    title: string
    size: keyof typeof SIZE_CLASSES
    className?: string
}

/** A scaled-down, non-interactive render of an email, for chips and picker cards. */
export function EmailPreviewThumbnail({ html, title, size, className }: EmailPreviewThumbnailProps): JSX.Element {
    return (
        <span className={cn('block shrink-0 overflow-hidden bg-white', SIZE_CLASSES[size], className)}>
            <iframe
                srcDoc={html}
                sandbox=""
                title={title}
                // The framed email is decorative: its own links would otherwise be tab stops with no
                // visible focus at this scale, and `pointer-events-none` covers the mouse only.
                tabIndex={-1}
                // `ph-no-capture`: the recorder serializes `srcdoc`, so without it the whole design
                // would ride into our own session recordings. Unreadable at this scale anyway.
                className="w-[600px] h-[1000px] origin-top-left scale-(--email-preview-scale) border-0 pointer-events-none ph-no-capture"
            />
        </span>
    )
}

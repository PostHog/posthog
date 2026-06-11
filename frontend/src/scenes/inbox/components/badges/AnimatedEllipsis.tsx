/**
 * Animated three-dot ellipsis used while the inbox is warming up.
 *
 * Desktop relied on an `inbox-ellipsis-dot` CSS class for the staggered bounce.
 * Cloud has no such global class, so we drive the same effect with Tailwind's
 * `animate-bounce` utility and per-dot `animationDelay` runtime values.
 */
export function AnimatedEllipsis(): JSX.Element {
    return (
        <span aria-hidden>
            <span className="inline-flex items-end gap-px leading-none">
                {[0, 150, 300].map((delay) => (
                    <span
                        key={delay}
                        className="animate-bounce"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ animationDelay: `${delay}ms`, animationDuration: '1s' }}
                    >
                        .
                    </span>
                ))}
            </span>
        </span>
    )
}

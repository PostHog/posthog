import './avatar.css'

import { Avatar as AvatarPrimitive } from '@base-ui/react/avatar'
import * as React from 'react'

import { cn } from './lib/utils'

type AvatarSize = 'default' | 'sm' | 'xs'

const Avatar = React.forwardRef<
    HTMLSpanElement,
    React.ComponentProps<typeof AvatarPrimitive.Root> & { size?: AvatarSize }
>(function Avatar({ className, size = 'default', ...props }, ref) {
    return (
        <AvatarPrimitive.Root
            ref={ref}
            data-quill
            data-slot="avatar"
            data-size={size}
            className={cn('quill-avatar', className)}
            {...props}
        />
    )
})

const AvatarImage = React.forwardRef<HTMLImageElement, React.ComponentProps<typeof AvatarPrimitive.Image>>(
    function AvatarImage({ className, ...props }, ref) {
        return (
            <AvatarPrimitive.Image
                ref={ref}
                data-slot="avatar-image"
                className={cn('quill-avatar__image', className)}
                {...props}
            />
        )
    }
)

const AvatarFallback = React.forwardRef<HTMLSpanElement, React.ComponentProps<typeof AvatarPrimitive.Fallback>>(
    function AvatarFallback({ className, ...props }, ref) {
        return (
            <AvatarPrimitive.Fallback
                ref={ref}
                data-slot="avatar-fallback"
                className={cn('quill-avatar__fallback', className)}
                {...props}
            />
        )
    }
)

// Overlapping pile of avatars. Inline (gapped) by default; `stacked` overlaps
// them and, on hover/focus, spreads them back to the inline gap. The spread is a
// `transform` (not margin/width), so the container box never changes — siblings
// don't reflow, the avatars just slide out over whatever sits beside them.
// `reverse` anchors the pile to its right edge and spreads left instead (and puts
// the rightmost avatar on top). `size` forwards to any Avatar child that doesn't
// set its own, and tunes the stacked overlap so small and default piles look right.
function AvatarGroup({
    className,
    stacked = false,
    reverse = false,
    size = 'default',
    children,
    style,
    ...props
}: React.ComponentProps<'div'> & { stacked?: boolean; reverse?: boolean; size?: AvatarSize }): React.ReactElement {
    const items = React.Children.toArray(children)
    return (
        <div
            data-quill
            data-slot="avatar-group"
            data-stacked={stacked ? '' : undefined}
            data-reverse={reverse ? '' : undefined}
            data-size={size}
            className={cn('quill-avatar-group', className)}
            // Count drives the z-order and the reverse spread math; declared last so
            // a caller's `style` can't clobber it.
            style={{ ...style, '--avatar-count': items.length } as React.CSSProperties}
            {...props}
        >
            {items.map((child, index) => {
                // Forward the group size to bare Avatar children (those without an
                // explicit size); leave anything else (a count chip, etc.) untouched.
                const content =
                    React.isValidElement<{ size?: AvatarSize }>(child) &&
                    child.type === Avatar &&
                    child.props.size === undefined
                        ? React.cloneElement(child, { size })
                        : child
                return (
                    <span
                        // The index drives the per-avatar hover translate; order is stable, so the index key is fine.
                        key={index}
                        data-slot="avatar-group-item"
                        className="quill-avatar-group__item"
                        style={{ '--avatar-index': index } as React.CSSProperties}
                    >
                        {content}
                    </span>
                )
            })}
        </div>
    )
}

Avatar.displayName = 'Avatar'
AvatarImage.displayName = 'AvatarImage'
AvatarFallback.displayName = 'AvatarFallback'

export { Avatar, AvatarImage, AvatarFallback, AvatarGroup }

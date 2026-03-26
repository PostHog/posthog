import './ScrollableShadows.scss'

import { ScrollArea } from '@base-ui/react/scroll-area'
import { clsx } from 'clsx'
import React, { CSSProperties, MutableRefObject } from 'react'

export type ScrollableShadowsProps = {
    children: React.ReactNode
    direction: 'horizontal' | 'vertical'
    className?: string
    innerClassName?: string
    scrollRef?: MutableRefObject<HTMLDivElement | null>
    tabIndex?: number
    role?: string
    ariaLabel?: string
    ariaActivedescendant?: string
    onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void
    onBlur?: () => void
    styledScrollbars?: boolean
    style?: CSSProperties
    /** Whether to disable scrolling. */
    disableScroll?: boolean
    /**
     * Whether scrolling should be constrained to the given direction.
     * When false, both axes are allowed to scroll.
     * Defaults to true for backwards compatibility.
     * Should be used in conjunction with direction
     */
    constrainToDirection?: boolean
    /** Whether to hide the scrollable shadows. */
    hideShadows?: boolean
    /** Whether to hide the scrollbars. */
    hideScrollbars?: boolean
}

export const ScrollableShadows = React.forwardRef<HTMLDivElement, ScrollableShadowsProps>(function ScrollableShadows(
    {
        children,
        direction,
        className,
        innerClassName,
        scrollRef,
        styledScrollbars = false,
        disableScroll = false,
        constrainToDirection = true,
        hideShadows = false,
        hideScrollbars = false,
        style,
        ...props
    },
    ref
) {
    return (
        <ScrollArea.Root
            ref={ref}
            className={clsx(
                'ScrollableShadows',
                `ScrollableShadows--${direction}`,
                hideShadows && 'ScrollableShadows--hide-shadows',
                hideScrollbars && 'ScrollableShadows--hide-scrollbars',
                className
            )}
            style={style}
            {...props}
        >
            <ScrollArea.Viewport
                ref={(el) => {
                    if (scrollRef) {
                        scrollRef.current = el
                    }
                }}
                className={clsx(
                    'ScrollableShadows__inner',
                    styledScrollbars && 'show-scrollbar-on-hover',
                    innerClassName,
                    disableScroll && 'overflow-hidden'
                )}
                style={
                    disableScroll
                        ? { overflow: 'hidden' }
                        : constrainToDirection
                          ? {
                                overflowX: direction === 'horizontal' ? undefined : 'hidden',
                                overflowY: direction === 'vertical' ? undefined : 'hidden',
                            }
                          : undefined
                }
            >
                <ScrollArea.Content className="min-w-0">{children}</ScrollArea.Content>
            </ScrollArea.Viewport>
        </ScrollArea.Root>
    )
})

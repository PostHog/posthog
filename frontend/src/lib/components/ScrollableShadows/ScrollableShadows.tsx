import './ScrollableShadows.scss'

import { ScrollArea } from '@base-ui/react/scroll-area'
import { clsx } from 'clsx'
import React, { CSSProperties, MutableRefObject } from 'react'

export type ScrollableShadowsProps = {
    children: React.ReactNode
    /**
     * Which axis to scroll and show shadows for.
     * When omitted, both axes can scroll and shadows appear on whichever axis overflows.
     */
    direction?: 'horizontal' | 'vertical'
    className?: string
    innerClassName?: string
    contentClassName?: string
    scrollRef?: MutableRefObject<HTMLDivElement | null>
    tabIndex?: number
    role?: string
    ariaLabel?: string
    ariaActivedescendant?: string
    onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void
    onFocusCapture?: (event: React.FocusEvent<HTMLDivElement>) => void
    onBlur?: () => void
    styledScrollbars?: boolean
    style?: CSSProperties
    /** Whether to disable scrolling. */
    disableScroll?: boolean
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
        contentClassName,
        scrollRef,
        styledScrollbars = false,
        disableScroll = false,
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
                        : direction
                          ? {
                                overflowX: direction === 'horizontal' ? undefined : 'hidden',
                                overflowY: direction === 'vertical' ? undefined : 'hidden',
                            }
                          : undefined
                }
            >
                <ScrollArea.Content className={clsx('min-w-0', contentClassName)}>{children}</ScrollArea.Content>
            </ScrollArea.Viewport>
        </ScrollArea.Root>
    )
})

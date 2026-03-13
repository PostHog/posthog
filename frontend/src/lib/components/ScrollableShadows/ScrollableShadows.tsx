import './ScrollableShadows.scss'

import { clsx } from 'clsx'
import React, { CSSProperties, MutableRefObject } from 'react'

import { useScrollable } from 'lib/hooks/useScrollable'

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
        hideShadows = false,
        hideScrollbars = false,
        ...props
    },
    ref
) {
    const {
        ref: scrollRefScrollable,
        isScrollableLeft,
        isScrollableRight,
        isScrollableBottom,
        isScrollableTop,
    } = useScrollable()

    return (
        <div
            className={clsx(
                'ScrollableShadows',
                `ScrollableShadows--${direction}`,
                !hideShadows && direction === 'horizontal' && isScrollableLeft && 'ScrollableShadows--left',
                !hideShadows && direction === 'horizontal' && isScrollableRight && 'ScrollableShadows--right',
                !hideShadows && direction === 'vertical' && isScrollableTop && 'ScrollableShadows--top',
                !hideShadows && direction === 'vertical' && isScrollableBottom && 'ScrollableShadows--bottom',
                hideScrollbars && 'ScrollableShadows--hide-scrollbars',
                className
            )}
            ref={ref}
            {...props}
        >
            <div
                className={clsx(
                    'ScrollableShadows__inner',
                    styledScrollbars && 'show-scrollbar-on-hover',
                    innerClassName,
                    disableScroll && 'overflow-hidden'
                )}
                ref={(refValue) => {
                    scrollRefScrollable.current = refValue
                    if (scrollRef) {
                        scrollRef.current = refValue
                    }
                }}
            >
                {children}
            </div>
        </div>
    )
})

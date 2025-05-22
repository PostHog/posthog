import './ScrollableShadows.scss'

import { clsx } from 'clsx'
import { useScrollable } from 'lib/hooks/useScrollable'
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
}

export const ScrollableShadows = React.forwardRef<HTMLDivElement, ScrollableShadowsProps>(function ScrollableShadows(
    { children, direction, className, innerClassName, scrollRef, styledScrollbars = false, ...props },
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

                direction === 'horizontal' && isScrollableLeft && 'ScrollableShadows--left',
                direction === 'horizontal' && isScrollableRight && 'ScrollableShadows--right',
                direction === 'vertical' && isScrollableTop && 'ScrollableShadows--top',
                direction === 'vertical' && isScrollableBottom && 'ScrollableShadows--bottom',
                className
            )}
            ref={ref}
            {...props}
        >
            <div
                className={clsx(
                    'ScrollableShadows__inner',
                    styledScrollbars && 'show-scrollbar-on-hover',
                    innerClassName
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

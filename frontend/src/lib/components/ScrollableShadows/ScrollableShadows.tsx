import './ScrollableShadows.scss'

import { useScrollable } from 'lib/hooks/useScrollable'
import { cn } from 'lib/utils/css-classes'
import React, { MutableRefObject } from 'react'

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
}

export const ScrollableShadows = React.forwardRef<HTMLDivElement, ScrollableShadowsProps>(function ScrollableShadows(
    { children, direction, className, innerClassName, scrollRef, ...props },
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
            className={cn(
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
                className={cn('ScrollableShadows__inner', innerClassName)}
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

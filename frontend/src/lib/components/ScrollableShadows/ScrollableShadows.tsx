import './ScrollableShadows.scss'

import { clsx } from 'clsx'
import { useScrollable } from 'lib/hooks/useScrollable'
import React, { MutableRefObject } from 'react'

export type ScrollableShadowsProps = {
    children: React.ReactNode
    direction: 'horizontal' | 'vertical'
    className?: string
    innerClassName?: string
    scrollRef?: MutableRefObject<HTMLDivElement | null>
}

export const ScrollableShadows = React.forwardRef<HTMLDivElement, ScrollableShadowsProps>(function ScrollableShadows(
    { children, direction, className, innerClassName, scrollRef },
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
        >
            <div
                className={clsx('ScrollableShadows__inner', innerClassName)}
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

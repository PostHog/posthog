import './ScrollableShadows.scss'

import { clsx } from 'clsx'
import { useScrollable } from 'lib/hooks/useScrollable'
import { MutableRefObject } from 'react'

export type ScrollableShadowsProps = {
    children: React.ReactNode
    direction: 'horizontal' | 'vertical'
    className?: string
    innerClassName?: string
    scrollRef?: MutableRefObject<HTMLDivElement | null>
}

export const ScrollableShadows = ({
    children,
    direction,
    className,
    innerClassName,
    scrollRef,
}: ScrollableShadowsProps): JSX.Element => {
    const { ref, isScrollableLeft, isScrollableRight, isScrollableBottom, isScrollableTop } = useScrollable()

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
        >
            <div
                className={clsx('ScrollableShadows__inner', innerClassName)}
                ref={(theRef) => {
                    ref.current = theRef
                    if (scrollRef) {
                        scrollRef.current = theRef
                    }
                }}
            >
                {children}
            </div>
        </div>
    )
}

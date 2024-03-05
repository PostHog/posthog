import './StickyView.scss'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import React, { useEffect, useRef, useState } from 'react'

export interface StickyViewProps {
    children: React.ReactNode
    top?: string
    marginTop?: number
}

export function StickyView({ children, top = '0px', marginTop = 0 }: StickyViewProps): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const { height, width } = useResizeObserver({ ref })
    const [fixed, setFixed] = useState(false)

    useEffect(() => {
        const onScroll = (): void => {
            const shouldFix = !!ref.current && ref.current.offsetTop - marginTop < window.scrollY
            if (shouldFix !== fixed) {
                setFixed(shouldFix)
            }
        }

        window.addEventListener('scroll', onScroll)

        return () => window.removeEventListener('scroll', onScroll)
    }, [fixed])

    return (
        <div
            className="StickyView"
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                height: `calc(100vh - ${top} - ${marginTop}px)`,
            }}
        >
            <div
                className="StickyView__sticker"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width,
                    height,
                    top,
                    position: fixed ? 'fixed' : undefined,
                    marginTop: fixed ? marginTop : undefined,
                }}
            >
                {children}
            </div>
        </div>
    )
}

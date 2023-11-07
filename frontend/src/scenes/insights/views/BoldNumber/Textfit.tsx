// Adapted from https://github.com/malte-wessel/react-textfit
// which is no longer maintained and does not support React 18

import { useEffect, useRef, useState } from 'react'

// Calculate width without padding.
const innerWidth = (el: HTMLDivElement): number => {
    const style = window.getComputedStyle(el, null)
    // Hidden iframe in Firefox returns null, https://github.com/malte-wessel/react-textfit/pull/34
    if (!style) {
        return el.clientWidth
    }

    return (
        el.clientWidth -
        parseInt(style.getPropertyValue('padding-left'), 10) -
        parseInt(style.getPropertyValue('padding-right'), 10)
    )
}

const assertElementFitsWidth = (el: HTMLDivElement, width: number): boolean => el.scrollWidth - 1 <= width

const Textfit = ({ min, max, children }: { min: number; max: number; children: React.ReactNode }): JSX.Element => {
    const parentRef = useRef<HTMLDivElement>(null)
    const childRef = useRef<HTMLDivElement>(null)

    const [fontSize, setFontSize] = useState<number>()

    let resizeTimer: NodeJS.Timeout

    const handleWindowResize = (): void => {
        clearTimeout(resizeTimer)
        resizeTimer = setTimeout(() => {
            const el = parentRef.current
            const wrapper = childRef.current

            if (el && wrapper) {
                const originalWidth = innerWidth(el)

                let mid
                let low = min
                let high = max

                while (low <= high) {
                    mid = Math.floor((low + high) / 2)
                    setFontSize(mid)

                    if (assertElementFitsWidth(wrapper, originalWidth)) {
                        low = mid + 1
                    } else {
                        high = mid - 1
                    }
                }
                mid = Math.min(low, high)

                // Ensure we hit the user-supplied limits
                mid = Math.max(mid, min)
                mid = Math.min(mid, max)

                setFontSize(mid)
            }
        }, 10)
    }

    useEffect(() => {
        window.addEventListener('resize', handleWindowResize)
        return () => window.removeEventListener('resize', handleWindowResize)
    }, [])

    useEffect(() => handleWindowResize(), [parentRef, childRef])

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={parentRef} style={{ lineHeight: 1, fontSize: fontSize }}>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div ref={childRef} style={{ whiteSpace: 'nowrap', display: 'inline-block' }}>
                {children}
            </div>
        </div>
    )
}

export default Textfit

import { useEffect, useRef, useState } from 'react'

import { TodayOverflowText } from '~/layout/today/TodayOverflowText'

export function TreeRowOverflowText({
    className,
    children,
}: {
    className?: string
    children: React.ReactNode
}): JSX.Element {
    const anchorRef = useRef<HTMLSpanElement>(null)
    const [isHovered, setIsHovered] = useState(false)
    const [isKeyboardFocused, setIsKeyboardFocused] = useState(false)

    useEffect(() => {
        const row = anchorRef.current?.closest('[role="treeitem"]')
        if (!row) {
            return
        }
        const onPointerEnter = (): void => setIsHovered(true)
        const onPointerLeave = (): void => setIsHovered(false)
        // A click also focuses the row. Only :focus-visible counts, so a click does not end the hover reveal.
        const onFocus = (): void => setIsKeyboardFocused(row.matches(':focus-visible'))
        const onBlur = (): void => setIsKeyboardFocused(false)
        row.addEventListener('pointerenter', onPointerEnter)
        row.addEventListener('pointerleave', onPointerLeave)
        row.addEventListener('focus', onFocus)
        row.addEventListener('blur', onBlur)
        return () => {
            row.removeEventListener('pointerenter', onPointerEnter)
            row.removeEventListener('pointerleave', onPointerLeave)
            row.removeEventListener('focus', onFocus)
            row.removeEventListener('blur', onBlur)
        }
    }, [])

    return (
        <span ref={anchorRef} className="contents">
            <TodayOverflowText reveal={isHovered || isKeyboardFocused} className={className}>
                {children}
            </TodayOverflowText>
        </span>
    )
}

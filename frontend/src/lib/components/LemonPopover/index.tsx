import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useOutsideClickHandler } from '../../hooks/useOutsideClickHandler'
import clsx from 'clsx'
import './LemonPopover.scss'

export type LemonPopoverPlacement = 'bottom-right' | 'bottom-left'

export interface LemonPopoverProps {
    /** Popover trigger element. */
    children: React.ReactElement
    /** Content of the popover itself. */
    content: React.ReactNode
    /** Where the popover should start relative to children. */
    placement?: LemonPopoverPlacement
    /** Whether the popover is actionable rather than just informative - actionable means a colored border. */
    actionable?: boolean
    /** Extra overlay style. */
    overlayStyle?: React.CSSProperties
}

export function LemonPopover({
    children,
    content,
    placement = 'bottom-right',
    actionable = false,
    overlayStyle,
}: LemonPopoverProps): JSX.Element {
    const [wasEverVisible, setWasEverVisible] = useState(false)
    const [isVisible, setIsVisible] = useState(false)
    const [popoverCoords, setPopoverCoords] = useState<[number, number]>([0, 0])

    const childrenRef = useRef<HTMLElement | null>(null)
    const popoverRef = useRef<HTMLDivElement | null>(null)

    useOutsideClickHandler([popoverRef.current, childrenRef.current], () => setIsVisible(false))

    useEffect(() => {
        // We use wasEverVisible to keep the popover always mounted after first showing
        // This way it's simpler to animate hiding and there's less work to be done when showing the popover again
        if (isVisible && !wasEverVisible) {
            setWasEverVisible(true)
        }
    }, [isVisible, wasEverVisible])

    const childrenLeft = childrenRef.current?.offsetLeft || 0
    const childrenTop = childrenRef.current?.offsetTop || 0
    const childrenWidth = childrenRef.current?.offsetWidth || 0
    const childrenHeight = childrenRef.current?.offsetHeight || 0

    const [popoverWidth, setPopoverWidth] = useState(0)
    const setPopoverRef = useCallback((node: HTMLDivElement | null) => {
        if (node) {
            setPopoverWidth(node.offsetWidth)
        }
        popoverRef.current = node
    }, [])

    useEffect(
        () =>
            setPopoverCoords([
                placement === 'bottom-right' ? childrenLeft + childrenWidth - popoverWidth : childrenLeft,
                childrenTop + childrenHeight,
            ]),
        [placement, isVisible, childrenLeft, childrenTop, childrenWidth, childrenHeight, popoverWidth]
    )

    return (
        <div className="LemonPopover__container">
            {React.cloneElement(children, {
                onClick: () => setIsVisible((state) => !state),
                ref: childrenRef,
                style: { cursor: 'pointer' },
            })}
            {wasEverVisible && (
                <div
                    className={clsx(
                        'LemonPopover__overlay',
                        actionable && 'LemonPopover__overlay--actionable',
                        !isVisible && 'LemonPopover__overlay--hidden',
                        `LemonPopover__overlay--${placement}`
                    )}
                    ref={setPopoverRef}
                    style={{ ...overlayStyle, left: popoverCoords[0], top: popoverCoords[1] }}
                >
                    {content}
                </div>
            )}
        </div>
    )
}

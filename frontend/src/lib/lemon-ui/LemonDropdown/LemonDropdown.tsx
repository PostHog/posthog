import React, { MouseEventHandler, useContext, useEffect, useRef, useState } from 'react'

import { Popover, PopoverOverlayContext, PopoverProps } from '../Popover'

// Hovering off the trigger towards the panel (or vice versa) briefly crosses a gap that is
// neither element - e.g. the arrow/offset area between a `placement="top"` panel and its
// trigger. Without a grace period, that gap closes the dropdown, which reopens it the moment
// the cursor lands back on the trigger, causing rapid flicker. This delay lets the close be
// cancelled if the cursor re-enters either the trigger or the panel before it fires.
const HOVER_CLOSE_DELAY_MS = 150

export interface LemonDropdownProps extends Omit<PopoverProps, 'children' | 'visible'> {
    visible?: boolean
    /**
     *  Setting `visible` shifts the component to controlled mode.
     *  This lets you choose whether to start open (Defaults to false).
     *  Without having to take control of the visibility state.
     *  */
    startVisible?: boolean
    onVisibilityChange?: (visible: boolean) => void
    /**
     * Whether the dropdown should be closed on click inside.
     * @default true
     */
    closeOnClickInside?: boolean
    /** @default 'click' */
    trigger?: 'click' | 'hover'
    children: React.ReactElement<
        Record<string, any> & {
            onClick: MouseEventHandler
            active?: boolean
            'aria-haspopup': Required<React.AriaAttributes>['aria-haspopup']
        }
    >
}

/** A wrapper that provides a dropdown for any element supporting `onClick`. Built on top of Popover. */
export const LemonDropdown = React.forwardRef<HTMLDivElement, LemonDropdownProps>(
    (
        {
            visible,
            onVisibilityChange,
            onClickOutside,
            onClickInside,
            onMouseLeaveInside,
            closeOnClickInside = true,
            trigger = 'click',
            children,
            startVisible,
            ...popoverProps
        },
        ref
    ) => {
        const isControlled = visible !== undefined

        const [, parentPopoverLevel] = useContext(PopoverOverlayContext)
        const [localVisible, setLocalVisible] = useState(visible ?? startVisible ?? false)

        const floatingRef = useRef<HTMLDivElement>(null)
        const referenceRef = useRef<HTMLSpanElement>(null)
        const closeTimeoutRef = useRef<number | null>(null)

        const effectiveVisible = visible ?? localVisible

        const setVisible = (value: boolean): void => {
            if (!isControlled) {
                setLocalVisible(value)
            }
            onVisibilityChange?.(value)
        }

        const cancelScheduledClose = (): void => {
            if (closeTimeoutRef.current !== null) {
                window.clearTimeout(closeTimeoutRef.current)
                closeTimeoutRef.current = null
            }
        }

        const scheduleClose = (): void => {
            cancelScheduledClose()
            closeTimeoutRef.current = window.setTimeout(() => {
                closeTimeoutRef.current = null
                setVisible(false)
            }, HOVER_CLOSE_DELAY_MS)
        }

        useEffect(() => cancelScheduledClose, [])

        return (
            <Popover
                ref={ref}
                floatingRef={floatingRef}
                referenceRef={referenceRef}
                onClickOutside={(e) => {
                    if (trigger === 'click') {
                        setVisible(false)
                    }
                    onClickOutside?.(e)
                }}
                onClickInside={(e) => {
                    e.stopPropagation()
                    closeOnClickInside && setVisible(false)
                    onClickInside?.(e)
                }}
                onMouseEnterInside={() => {
                    if (trigger === 'hover') {
                        cancelScheduledClose()
                    }
                }}
                onMouseLeaveInside={(e) => {
                    // relatedTarget is null when leaving the window and isn't always a Node, so
                    // Node.contains() would throw — treat anything that isn't a contained Node as "left".
                    const relatedTarget = e.relatedTarget
                    if (
                        trigger === 'hover' &&
                        !(relatedTarget instanceof Node && referenceRef.current?.contains(relatedTarget))
                    ) {
                        scheduleClose()
                    }
                    onMouseLeaveInside?.(e)
                }}
                visible={effectiveVisible}
                {...popoverProps}
            >
                {React.cloneElement(children, {
                    onClick: (e: React.MouseEvent): void => {
                        cancelScheduledClose()
                        setVisible(!effectiveVisible)
                        children.props.onClick?.(e)
                        if (parentPopoverLevel > -1) {
                            // If this button is inside another popover, let's not propagate this event so that
                            // the parent popover doesn't close
                            e.stopPropagation()
                        }
                    },
                    onMouseEnter: (): void => {
                        if (trigger === 'hover') {
                            cancelScheduledClose()
                            setVisible(true)
                        }
                    },
                    onMouseLeave: (e: React.MouseEvent): void => {
                        const relatedTarget = e.relatedTarget
                        if (
                            trigger === 'hover' &&
                            !(relatedTarget instanceof Node && floatingRef.current?.contains(relatedTarget))
                        ) {
                            scheduleClose()
                        }
                    },
                    'aria-haspopup': 'true',
                })}
            </Popover>
        )
    }
)
LemonDropdown.displayName = 'Dropdown'

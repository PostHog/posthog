import { useValues } from 'kea'
import { router } from 'kea-router'
import React, { MouseEventHandler, useContext, useEffect, useRef, useState } from 'react'

import { Popover, PopoverOverlayContext, PopoverProps } from '../Popover'

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
    hoverOpenDelayMs?: number
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
            hoverOpenDelayMs = 0,
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
        const hoverOpenTimeoutRef = useRef<number | null>(null)

        const clearHoverOpenTimeout = (): void => {
            if (hoverOpenTimeoutRef.current !== null) {
                window.clearTimeout(hoverOpenTimeoutRef.current)
                hoverOpenTimeoutRef.current = null
            }
        }

        useEffect(
            () => () => {
                if (hoverOpenTimeoutRef.current !== null) {
                    window.clearTimeout(hoverOpenTimeoutRef.current)
                }
            },
            []
        )

        const effectiveVisible = visible ?? localVisible

        const setVisible = (value: boolean): void => {
            if (!isControlled) {
                setLocalVisible(value)
            }
            onVisibilityChange?.(value)
        }

        // Read at unmount to notify controlled parents that a still-open hover popover is gone.
        const effectiveVisibleRef = useRef(effectiveVisible)
        effectiveVisibleRef.current = effectiveVisible
        useEffect(
            () => () => {
                if (trigger === 'hover' && effectiveVisibleRef.current) {
                    onVisibilityChange?.(false)
                }
            },
            [] // oxlint-disable-line react-hooks/exhaustive-deps
        )

        return (
            <>
                {/* Only an open hover popover watches for route changes, so the router
                    subscription stays off the common click-dropdown path. */}
                {trigger === 'hover' && effectiveVisible && (
                    <HoverPopoverRouteDismissal onDismiss={() => setVisible(false)} />
                )}
                <Popover
                    ref={ref}
                    floatingRef={floatingRef}
                    referenceRef={referenceRef}
                    onClickOutside={(e) => {
                        // A hover popover stays open on an outside click (it closes on mouseleave),
                        // but Escape — delivered here by the Popover's floating-ui dismiss — must
                        // still close it so it cannot outlive its page.
                        if (trigger === 'click' || (e instanceof KeyboardEvent && e.key === 'Escape')) {
                            setVisible(false)
                        }
                        onClickOutside?.(e)
                    }}
                    onClickInside={(e) => {
                        e.stopPropagation()
                        closeOnClickInside && setVisible(false)
                        onClickInside?.(e)
                    }}
                    onMouseLeaveInside={(e) => {
                        // relatedTarget is null when leaving the window and isn't always a Node, so
                        // Node.contains() would throw — treat anything that isn't a contained Node as "left".
                        const relatedTarget = e.relatedTarget
                        if (
                            trigger === 'hover' &&
                            !(relatedTarget instanceof Node && referenceRef.current?.contains(relatedTarget))
                        ) {
                            setVisible(false)
                        }
                        onMouseLeaveInside?.(e)
                    }}
                    visible={effectiveVisible}
                    {...popoverProps}
                >
                    {React.cloneElement(children, {
                        onClick: (e: React.MouseEvent): void => {
                            clearHoverOpenTimeout()
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
                                clearHoverOpenTimeout()
                                if (hoverOpenDelayMs > 0) {
                                    hoverOpenTimeoutRef.current = window.setTimeout(() => {
                                        hoverOpenTimeoutRef.current = null
                                        setVisible(true)
                                    }, hoverOpenDelayMs)
                                } else {
                                    setVisible(true)
                                }
                            }
                        },
                        onMouseLeave: (e: React.MouseEvent): void => {
                            clearHoverOpenTimeout()
                            const relatedTarget = e.relatedTarget
                            if (
                                trigger === 'hover' &&
                                !(relatedTarget instanceof Node && floatingRef.current?.contains(relatedTarget))
                            ) {
                                setVisible(false)
                            }
                        },
                        'aria-haspopup': 'true',
                    })}
                </Popover>
            </>
        )
    }
)
LemonDropdown.displayName = 'Dropdown'

// Rendered only while a hover popover is open. A hover overlay lives in a portal and closes only
// on a real mouseleave, so on its own it can outlive the page it anchored to. This closes it when
// the route changes — following a link inside it or switching projects moves the page without ever
// moving the cursor.
function HoverPopoverRouteDismissal({ onDismiss }: { onDismiss: () => void }): null {
    const { currentLocation } = useValues(router)
    const initialPathnameRef = useRef(currentLocation.pathname)
    const onDismissRef = useRef(onDismiss)
    onDismissRef.current = onDismiss

    useEffect(() => {
        if (currentLocation.pathname !== initialPathnameRef.current) {
            onDismissRef.current()
        }
    }, [currentLocation.pathname])

    return null
}

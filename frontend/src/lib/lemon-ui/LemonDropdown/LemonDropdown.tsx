import React, { MouseEventHandler, useContext, useRef, useState } from 'react'

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
    /**
     * Which interactions open the dropdown. Pass an array to combine — e.g. `['hover', 'click']`
     * keeps the popover open during hover and also lets touch users tap to open.
     * @default 'click'
     */
    trigger?: 'click' | 'hover' | Array<'click' | 'hover'>
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

        const effectiveVisible = visible ?? localVisible

        // Legacy single-string triggers always toggle visibility on click (preserving prior behavior
        // for existing callers). The new array form lets a caller combine hover and click, in which
        // case click only opens — so a hover-opened popover doesn't immediately dead-click closed.
        const isArrayTrigger = Array.isArray(trigger)
        const triggers = isArrayTrigger ? trigger : [trigger]
        const hasClickTrigger = !isArrayTrigger || triggers.includes('click')
        const hasHoverTrigger = isArrayTrigger ? triggers.includes('hover') : trigger === 'hover'
        const clickOnlyOpens = isArrayTrigger && hasHoverTrigger && triggers.includes('click')

        const setVisible = (value: boolean): void => {
            if (!isControlled) {
                setLocalVisible(value)
            }
            onVisibilityChange?.(value)
        }

        return (
            <Popover
                ref={ref}
                floatingRef={floatingRef}
                referenceRef={referenceRef}
                onClickOutside={(e) => {
                    // Match prior single-string 'click' behavior; array form closes when 'click' is present.
                    if (isArrayTrigger ? triggers.includes('click') : trigger === 'click') {
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
                    if (hasHoverTrigger && !referenceRef.current?.contains(e.relatedTarget as Node)) {
                        setVisible(false)
                    }
                    onMouseLeaveInside?.(e)
                }}
                visible={effectiveVisible}
                {...popoverProps}
            >
                {React.cloneElement(children, {
                    onClick: (e: React.MouseEvent): void => {
                        if (hasClickTrigger) {
                            // In combined hover+click mode, click only opens — hover/mouse-leave or
                            // click-outside handle dismissal. Avoids the dead-click feel where clicking
                            // a hover-opened popover immediately closes it.
                            setVisible(clickOnlyOpens ? true : !effectiveVisible)
                        }
                        children.props.onClick?.(e)
                        if (parentPopoverLevel > -1) {
                            // If this button is inside another popover, let's not propagate this event so that
                            // the parent popover doesn't close
                            e.stopPropagation()
                        }
                    },
                    onMouseEnter: (): void => {
                        if (hasHoverTrigger) {
                            setVisible(true)
                        }
                    },
                    onMouseLeave: (e: React.MouseEvent): void => {
                        if (hasHoverTrigger && !floatingRef.current?.contains(e.relatedTarget as Node)) {
                            setVisible(false)
                        }
                    },
                    'aria-haspopup': 'true',
                })}
            </Popover>
        )
    }
)
LemonDropdown.displayName = 'Dropdown'

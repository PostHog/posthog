import React, { MouseEventHandler, useContext, useRef, useState } from 'react'

import { Popover, PopoverOverlayContext, PopoverProps } from '../Popover'

export interface LemonDropdownProps extends Omit<PopoverProps, 'children' | 'visible'> {
    visible?: boolean
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
    /** Any other refs that needs to be taken into account for handling outside clicks e.g. other nested popovers. */
    additionalRefs?: React.MutableRefObject<HTMLDivElement | null>[]
}

/** A wrapper that provides a dropdown for any element supporting `onClick`. Built on top of Popover. */
export const LemonDropdown: React.FunctionComponent<LemonDropdownProps & React.RefAttributes<HTMLDivElement>> =
    React.forwardRef<HTMLDivElement, LemonDropdownProps>(
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
                additionalRefs = [],
                ...popoverProps
            },
            ref
        ) => {
            const isControlled = visible !== undefined

            const [, parentPopoverLevel] = useContext(PopoverOverlayContext)
            const [localVisible, setLocalVisible] = useState(visible ?? false)

            const floatingRef = useRef<HTMLDivElement>(null)
            const referenceRef = useRef<HTMLSpanElement>(null)

            const effectiveVisible = visible ?? localVisible

            const setVisible = (value: boolean): void => {
                if (!isControlled) {
                    setLocalVisible(value)
                }
                onVisibilityChange?.(value)
            }

            return (
                <Popover
                    ref={ref}
                    additionalRefs={additionalRefs}
                    floatingRef={floatingRef}
                    referenceRef={referenceRef}
                    onClickOutside={(e) => {
                        console.log('abcde onClickOutside detected', e)
                        if (trigger === 'click') {
                            setVisible(false)
                        }
                        onClickOutside?.(e)
                    }}
                    onClickInside={(e) => {
                        console.log('abcde onClickInside detected', e)
                        e.stopPropagation()
                        closeOnClickInside && setVisible(false)
                        onClickInside?.(e)
                    }}
                    onMouseLeaveInside={(e) => {
                        if (trigger === 'hover' && !referenceRef.current?.contains(e.relatedTarget as Node)) {
                            setVisible(false)
                        }
                        onMouseLeaveInside?.(e)
                    }}
                    visible={effectiveVisible}
                    {...popoverProps}
                >
                    {React.cloneElement(children, {
                        onClick: (e: React.MouseEvent): void => {
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
                                setVisible(true)
                            }
                        },
                        onMouseLeave: (e: React.MouseEvent): void => {
                            if (trigger === 'hover' && !floatingRef.current?.contains(e.relatedTarget as Node)) {
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

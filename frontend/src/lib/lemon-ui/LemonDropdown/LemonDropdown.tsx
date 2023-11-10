import React, { MouseEventHandler, useContext, useEffect, useRef, useState } from 'react'
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
                ...popoverProps
            },
            ref
        ) => {
            const [, parentPopoverLevel] = useContext(PopoverOverlayContext)
            const [localVisible, setLocalVisible] = useState(false)

            const floatingRef = useRef<HTMLDivElement>(null)
            const referenceRef = useRef<HTMLSpanElement>(null)

            const effectiveVisible = visible ?? localVisible

            useEffect(() => {
                onVisibilityChange?.(effectiveVisible)
            }, [effectiveVisible, onVisibilityChange])

            return (
                <Popover
                    ref={ref}
                    floatingRef={floatingRef}
                    referenceRef={referenceRef}
                    onClickOutside={(e) => {
                        if (trigger === 'click') {
                            setLocalVisible(false)
                        }
                        onClickOutside?.(e)
                    }}
                    onClickInside={(e) => {
                        e.stopPropagation()
                        closeOnClickInside && setLocalVisible(false)
                        onClickInside?.(e)
                    }}
                    onMouseLeaveInside={(e) => {
                        if (trigger === 'hover' && !referenceRef.current?.contains(e.relatedTarget as Node)) {
                            setLocalVisible(false)
                        }
                        onMouseLeaveInside?.(e)
                    }}
                    visible={effectiveVisible}
                    {...popoverProps}
                >
                    {React.cloneElement(children, {
                        onClick: (e: React.MouseEvent): void => {
                            setLocalVisible((state) => !state)
                            children.props.onClick?.(e)
                            if (parentPopoverLevel > -1) {
                                // If this button is inside another popover, let's not propagate this event so that
                                // the parent popover doesn't close
                                e.stopPropagation()
                            }
                        },
                        onMouseEnter: (): void => {
                            if (trigger === 'hover') {
                                setLocalVisible(true)
                            }
                        },
                        onMouseLeave: (e: React.MouseEvent): void => {
                            if (trigger === 'hover' && !floatingRef.current?.contains(e.relatedTarget as Node)) {
                                setLocalVisible(false)
                            }
                        },
                        'aria-haspopup': 'true',
                    })}
                </Popover>
            )
        }
    )
LemonDropdown.displayName = 'Dropdown'

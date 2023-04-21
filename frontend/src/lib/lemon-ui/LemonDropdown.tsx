import React, { MouseEventHandler, useContext, useEffect, useState } from 'react'
import { Popover, PopoverLevelContext, PopoverProps } from './Popover'

export interface LemonDropdownProps extends Omit<PopoverProps, 'children' | 'visible'> {
    visible?: boolean
    onVisibilityChange?: (visible: boolean) => void
    /**
     * Whether the dropdown should be closed on click inside.
     * @default true
     */
    closeOnClickInside?: boolean
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
                closeOnClickInside = true,
                children,
                ...popoverProps
            },
            ref
        ) => {
            const popoverLevel = useContext(PopoverLevelContext)
            const [localVisible, setLocalVisible] = useState(false)

            const effectiveVisible = visible ?? localVisible

            useEffect(() => {
                onVisibilityChange?.(effectiveVisible)
            }, [effectiveVisible, onVisibilityChange])

            return (
                <Popover
                    ref={ref}
                    onClickOutside={(e) => {
                        setLocalVisible(false)
                        onClickOutside?.(e)
                    }}
                    onClickInside={(e) => {
                        e.stopPropagation()
                        closeOnClickInside && setLocalVisible(false)
                        onClickInside?.(e)
                    }}
                    visible={effectiveVisible}
                    {...popoverProps}
                >
                    {React.cloneElement(children, {
                        onClick: (e: React.MouseEvent): void => {
                            setLocalVisible((state) => !state)
                            children.props.onClick?.(e)
                            if (popoverLevel > 0) {
                                // If this button is inside another popover, let's not propagate this event so that
                                // the parent popover doesn't close
                                e.stopPropagation()
                            }
                        },
                        'aria-haspopup': 'true',
                    })}
                </Popover>
            )
        }
    )
LemonDropdown.displayName = 'Dropdown'

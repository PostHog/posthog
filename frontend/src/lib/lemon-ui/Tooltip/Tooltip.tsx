import {
    arrow,
    autoUpdate,
    flip,
    FloatingPortal,
    offset,
    Placement,
    shift,
    useDismiss,
    useFloating,
    useFocus,
    useHover,
    useInteractions,
    useRole,
} from '@floating-ui/react'
import clsx from 'clsx'
import React, { useRef, useState } from 'react'

const DEFAULT_DELAY_MS = 500

export type TooltipProps = {
    title: string | React.ReactNode
    children: JSX.Element
    open?: boolean
    delayMs?: number
    placement?: Placement
    className?: string
}

export const Tooltip = ({
    title,
    children,
    open,
    placement = 'top',
    delayMs = DEFAULT_DELAY_MS,
    className = '',
}: TooltipProps): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)
    const caretRef = useRef(null)

    const { refs, floatingStyles, context, middlewareData } = useFloating({
        open: open === undefined ? isOpen : open,
        onOpenChange: !open ? setIsOpen : undefined,
        placement: placement,
        whileElementsMounted: autoUpdate,
        middleware: [
            offset(5),
            flip({
                fallbackAxisSideDirection: 'start',
            }),
            shift(),
            arrow({ element: caretRef }),
        ],
    })

    const hover = useHover(context, { move: false, restMs: delayMs })
    const focus = useFocus(context)
    const dismiss = useDismiss(context)
    const role = useRole(context, { role: 'tooltip' })
    const { getReferenceProps, getFloatingProps } = useInteractions([hover, focus, dismiss, role])

    const child = React.isValidElement(children) ? children : <span>{children}</span>

    const placementSide = placement.split('-')[0]
    const staticSide =
        {
            top: 'bottom',
            right: 'left',
            bottom: 'top',
            left: 'right',
        }[placementSide] || 'top'

    return title ? (
        <>
            {React.cloneElement(child, {
                ref: refs.setReference,
                ...getReferenceProps(),
            })}
            <FloatingPortal>
                {isOpen && (
                    <>
                        <div
                            ref={refs.setFloating}
                            className={clsx(
                                'bg-tooltip-bg py-1.5 px-2 z-[1070] break-words rounded text-start text-white',
                                className
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={floatingStyles}
                            {...getFloatingProps()}
                        >
                            {title}
                            <div
                                ref={caretRef}
                                className="absolute w-1.5 h-1.5 bg-tooltip-bg rotate-45"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    left: middlewareData.arrow?.x != null ? `${middlewareData.arrow.x}px` : '',
                                    top: middlewareData.arrow?.y != null ? `${middlewareData.arrow.y}px` : '',
                                    // Ensure the static side gets unset when
                                    // flipping to other placements' axes.
                                    right: '',
                                    bottom: '',
                                    [staticSide]: `-3px`,
                                }}
                            />
                        </div>
                    </>
                )}
            </FloatingPortal>
        </>
    ) : (
        children
    )
}

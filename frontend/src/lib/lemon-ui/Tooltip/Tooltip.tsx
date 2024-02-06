import {
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
import React, { useState } from 'react'

const DEFAULT_DELAY_MS = 500

export type TooltipProps = {
    title: string | React.ReactNode
    children?: React.ReactNode
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

    const { refs, floatingStyles, context } = useFloating({
        open: isOpen,
        onOpenChange: setIsOpen,
        placement: placement,
        whileElementsMounted: autoUpdate,
        middleware: [
            offset(5),
            flip({
                fallbackAxisSideDirection: 'start',
            }),
            shift(),
        ],
    })

    const hover = useHover(context, { move: false, restMs: delayMs })
    const focus = useFocus(context)
    const dismiss = useDismiss(context)
    const role = useRole(context, { role: 'tooltip' })
    const { getReferenceProps, getFloatingProps } = useInteractions([hover, focus, dismiss, role])

    const child = React.isValidElement(children) ? children : <span>{children}</span>

    return (
        <>
            {React.cloneElement(child, {
                ref: refs.setReference,
                ...getReferenceProps(),
            })}
            <FloatingPortal>
                {isOpen && (
                    <div
                        ref={refs.setFloating}
                        className={clsx('bg-tooltip-bg py-1 px-2 break-words rounded text-start', className)}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={floatingStyles}
                        {...getFloatingProps()}
                    >
                        {title}
                    </div>
                )}
            </FloatingPortal>
        </>
    )
}

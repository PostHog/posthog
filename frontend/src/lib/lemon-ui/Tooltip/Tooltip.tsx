import {
    arrow,
    autoUpdate,
    flip,
    FloatingArrow,
    FloatingPortal,
    offset as offsetFunc,
    Placement,
    shift,
    useDismiss,
    useFloating,
    useFocus,
    useHover,
    useInteractions,
    useMergeRefs,
    useRole,
} from '@floating-ui/react'
import clsx from 'clsx'
import React, { useRef, useState } from 'react'

const DEFAULT_DELAY_MS = 500

export type TooltipProps = {
    title: string | React.ReactNode | (() => string)
    children: JSX.Element
    open?: boolean
    delayMs?: number
    offset?: number
    placement?: Placement
    className?: string
}

export function Tooltip({
    title,
    children,
    open,
    placement = 'top',
    offset = 8,
    delayMs = DEFAULT_DELAY_MS,
    className = '',
}: TooltipProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const caretRef = useRef(null)

    const { refs, floatingStyles, context } = useFloating({
        open: open === undefined ? isOpen : open,
        onOpenChange: !open ? setIsOpen : undefined,
        placement: placement,
        whileElementsMounted: autoUpdate,
        middleware: [
            offsetFunc(offset),
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

    const childrenRef = (children as any).ref

    const triggerRef = useMergeRefs([refs.setReference, childrenRef])

    return title ? (
        <>
            {React.cloneElement(
                child,
                getReferenceProps({
                    ref: triggerRef,
                })
            )}
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
                            {typeof title === 'function' ? title() : title}
                            <FloatingArrow ref={caretRef} context={context} fill="var(--tooltip-bg)" />
                        </div>
                    </>
                )}
            </FloatingPortal>
        </>
    ) : (
        children
    )
}

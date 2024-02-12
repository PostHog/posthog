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
import { CSSTransition } from 'react-transition-group'

interface TooltipProps {
    title: string | React.ReactNode | (() => string)
    children: JSX.Element
    delayMs?: number
    offset?: number
    placement?: Placement
    className?: string
}

export function Tooltip({
    children,
    title,
    className = '',
    placement = 'top',
    offset = 8,
    delayMs = 500,
}: TooltipProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const caretRef = useRef(null)

    const { context, refs } = useFloating({
        placement,
        open,
        onOpenChange: setOpen,
        whileElementsMounted: autoUpdate,
        middleware: [
            offsetFunc(offset),
            flip({ fallbackAxisSideDirection: 'start' }),
            shift(),
            arrow({ element: caretRef }),
        ],
    })

    const hover = useHover(context, {
        move: false,
        delay: {
            open: delayMs,
            close: 0,
        },
    })
    const focus = useFocus(context)
    const dismiss = useDismiss(context)
    const role = useRole(context, { role: 'tooltip' })

    const { getFloatingProps, getReferenceProps } = useInteractions([hover, focus, dismiss, role])

    const childrenRef = (children as any).ref
    const triggerRef = useMergeRefs([refs.setReference, childrenRef])

    const child = React.isValidElement(children) ? children : <span>{children}</span>

    const clonedChild = React.cloneElement(
        child,
        getReferenceProps({
            ref: triggerRef,
            ...child.props,
        })
    )

    return title ? (
        <>
            {clonedChild}
            <FloatingPortal>
                <CSSTransition in={open} timeout={50} classNames="Tooltip-" appear mountOnEnter unmountOnExit>
                    <div
                        ref={refs.setFloating}
                        className={clsx(
                            'bg-tooltip-bg py-1.5 px-2 z-[1070] break-words rounded text-start text-white',
                            className
                        )}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ ...context.floatingStyles }}
                        {...getFloatingProps()}
                    >
                        {typeof title === 'function' ? title() : title}
                        <FloatingArrow ref={caretRef} context={context} width={8} height={4} fill="var(--tooltip-bg)" />
                    </div>
                </CSSTransition>
            </FloatingPortal>
        </>
    ) : (
        children
    )
}

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
    useTransitionStyles,
} from '@floating-ui/react'
import clsx from 'clsx'
import React, { useRef, useState } from 'react'

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

    const { styles: transitionStyles } = useTransitionStyles(context, {
        duration: {
            open: 200,
            close: 0,
        },
        initial: ({ side }) => ({
            opacity: 0,
            transform: {
                top: 'translateY(3px)',
                bottom: 'translateY(-3px)',
                left: 'translateX(3px)',
                right: 'translateX(-3px)',
            }[side],
        }),
    })

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
            {open && (
                <FloatingPortal>
                    <div
                        ref={refs.setFloating}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ ...context.floatingStyles }}
                        {...getFloatingProps()}
                    >
                        <div
                            className={clsx(
                                'bg-tooltip-bg py-1.5 px-2 z-[1070] break-words rounded text-start text-white',
                                className
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ ...transitionStyles }}
                        >
                            {typeof title === 'function' ? title() : title}
                            <FloatingArrow
                                ref={caretRef}
                                context={context}
                                width={8}
                                height={4}
                                fill="var(--tooltip-bg)"
                            />
                        </div>
                    </div>
                </FloatingPortal>
            )}
        </>
    ) : (
        children
    )
}

import './Tooltip.scss'

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
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import React, { useRef, useState } from 'react'

export interface TooltipProps {
    title: string | React.ReactNode | (() => string)
    children: JSX.Element
    delayMs?: number
    closeDelayMs?: number
    offset?: number
    arrowOffset?: number
    placement?: Placement
    className?: string
    visible?: boolean
}

export const Tooltip = React.forwardRef<HTMLElement, TooltipProps>(function Tooltip(
    {
        children,
        title,
        className = '',
        placement = 'top',
        offset = 8,
        arrowOffset,
        delayMs = 500,
        closeDelayMs = 0, // Set this to some delay to ensure the content stays open when hovered
        visible: controlledOpen,
    }: TooltipProps,
    ref
): JSX.Element {
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const caretRef = useRef(null)
    const floatingContainer = useFloatingContainer()

    const open = controlledOpen ?? uncontrolledOpen

    const { context, refs } = useFloating({
        placement,
        open,
        onOpenChange: setUncontrolledOpen,
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
            close: closeDelayMs,
        },
    })
    const focus = useFocus(context)
    const dismiss = useDismiss(context)
    const role = useRole(context, { role: 'tooltip' })

    const { getFloatingProps, getReferenceProps } = useInteractions([hover, focus, dismiss, role])

    const { styles: transitionStyles } = useTransitionStyles(context, {
        duration: {
            open: 150,
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
    const triggerRef = useMergeRefs([refs.setReference, childrenRef, ref])

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
                <FloatingPortal root={floatingContainer}>
                    <div
                        ref={refs.setFloating}
                        className="Tooltip max-w-sm"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ ...context.floatingStyles }}
                        {...getFloatingProps()}
                    >
                        <div
                            className={clsx(
                                'bg-[var(--tooltip-bg)] py-1.5 px-2 break-words rounded text-start text-white',
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
                                staticOffset={arrowOffset}
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
})

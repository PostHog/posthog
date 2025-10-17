import './Tooltip.scss'

import {
    FloatingArrow,
    FloatingPortal,
    Placement,
    arrow,
    autoUpdate,
    flip,
    offset as offsetFunc,
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
import React, { useEffect, useRef, useState } from 'react'
import { twMerge } from 'tailwind-merge'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'

import { Link } from '../Link'

export type TooltipTitle = string | React.ReactNode | (() => string)

export interface TooltipProps extends BaseTooltipProps {
    title?: TooltipTitle
}

interface BaseTooltipProps {
    delayMs?: number
    closeDelayMs?: number
    offset?: number
    arrowOffset?: number | ((placement: Placement) => number)
    placement?: Placement
    fallbackPlacements?: Placement[]
    className?: string
    containerClassName?: string
    visible?: boolean
    /**
     * Defaults to true if docLink is provided
     */
    interactive?: boolean
    docLink?: string
    /**
     * Run a function when showing the tooltip, for example to log an event.
     */
    onOpen?: () => void
}

export type RequiredTooltipProps = (
    | { title: TooltipTitle; docLink?: string }
    | { title?: TooltipTitle; docLink: string }
) &
    BaseTooltipProps

export function Tooltip({
    children,
    title,
    className = '',
    placement = 'top',
    fallbackPlacements,
    offset = 8,
    arrowOffset,
    delayMs = 500,
    closeDelayMs = 100, // Slight delay to ensure smooth transition
    interactive = false,
    visible: controlledOpen,
    docLink,
    containerClassName,
    onOpen,
}: React.PropsWithChildren<RequiredTooltipProps>): JSX.Element {
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const [isHoveringTooltip, setIsHoveringTooltip] = useState(false) // Track tooltip hover state
    const [isPressingReference, setIsPressingReference] = useState(false) // Track reference hover state
    const caretRef = useRef(null)
    const floatingContainer = useFloatingContainer()

    const open = controlledOpen ?? (uncontrolledOpen || isHoveringTooltip)

    useEffect(() => {
        if (open && onOpen) {
            onOpen()
        }
    }, [open, onOpen])

    const { context, refs } = useFloating({
        placement,
        open,
        onOpenChange: setUncontrolledOpen,
        whileElementsMounted: autoUpdate,
        middleware: [
            offsetFunc(offset),
            flip({ fallbackPlacements, fallbackAxisSideDirection: 'start' }),
            shift({ padding: 4 }),
            arrow({ element: caretRef }),
        ],
    })

    const hover = useHover(context, {
        enabled: !isPressingReference, // Need to disable esp. for elements where the tooltip is a dragging handle
        move: false,
        delay: {
            open: delayMs,
            close: closeDelayMs,
        },
    })
    const focus = useFocus(context)
    const dismiss = useDismiss(context, {
        referencePress: true, // referencePress closes tooltip on click
    })
    const role = useRole(context, { role: 'tooltip' })

    const { getFloatingProps, getReferenceProps } = useInteractions([hover, focus, dismiss, role])

    const { isMounted, styles: transitionStyles } = useTransitionStyles(context, {
        duration: {
            open: 100,
            close: 50,
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
            ...child.props,
            ref: triggerRef,
            onMouseDown: () => {
                setIsPressingReference(true)
                child.props.onMouseEnter?.()
            },
            onMouseUp: () => {
                setIsPressingReference(false)
                child.props.onMouseUp?.()
            },
        })
    )

    if (!title && !docLink) {
        return <>{child}</>
    }

    const isInteractive = interactive || !!docLink

    return (
        <>
            {clonedChild}
            {isMounted && (
                <FloatingPortal root={floatingContainer}>
                    <div
                        ref={refs.setFloating}
                        className={twMerge('Tooltip max-w-sm', containerClassName)}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ ...context.floatingStyles }}
                        {...getFloatingProps({
                            onMouseEnter: () => isInteractive && setIsHoveringTooltip(true), // Keep tooltip open
                            onMouseLeave: () => isInteractive && setIsHoveringTooltip(false), // Allow closing
                        })}
                    >
                        <div
                            className={clsx('bg-surface-tooltip py-1.5 px-2 break-words rounded text-start', className)}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ ...transitionStyles }}
                        >
                            {typeof title === 'function' ? title() : title}
                            {docLink && (
                                <p className={`mb-0 ${title ? 'mt-1' : ''}`}>
                                    <Link
                                        to={docLink}
                                        target="_blank"
                                        className="text-xs"
                                        data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                                        data-ph-capture-attribute-doclink={docLink}
                                    >
                                        Read the docs
                                    </Link>
                                </p>
                            )}
                            <FloatingArrow
                                ref={caretRef}
                                context={context}
                                width={8}
                                height={4}
                                staticOffset={
                                    typeof arrowOffset === 'function' ? arrowOffset(context.placement) : arrowOffset
                                }
                                fill="var(--color-bg-surface-tooltip)"
                            />
                        </div>
                    </div>
                </FloatingPortal>
            )}
        </>
    )
}

import './Tooltip.scss'

import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
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

import { FEATURE_FLAGS } from 'lib/constants'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'

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

type Side = 'top' | 'bottom' | 'left' | 'right'
type Align = 'start' | 'center' | 'end'

function placementToSideAlign(placement: Placement): { side: Side; align: Align } {
    const parts = placement.split('-')
    const side = parts[0] as Side
    const alignPart = parts[1] as 'start' | 'end' | undefined

    let align: Align = 'center'
    if (alignPart === 'start') {
        align = 'start'
    } else if (alignPart === 'end') {
        align = 'end'
    }

    return { side, align }
}

function TooltipLegacy({
    children,
    title,
    className = '',
    placement = 'top',
    fallbackPlacements,
    offset = 8,
    arrowOffset,
    delayMs = 500,
    closeDelayMs = 100,
    interactive = false,
    visible: controlledOpen,
    docLink,
    containerClassName,
    onOpen,
}: React.PropsWithChildren<RequiredTooltipProps>): JSX.Element {
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const [isHoveringTooltip, setIsHoveringTooltip] = useState(false)
    const [isPressingReference, setIsPressingReference] = useState(false)
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

    useEffect(() => {
        return () => {
            refs.setReference(null)
            refs.setFloating(null)
        }
    }, [refs])

    const hover = useHover(context, {
        enabled: !isPressingReference,
        move: false,
        delay: {
            open: delayMs,
            close: closeDelayMs,
        },
    })
    const focus = useFocus(context)
    const dismiss = useDismiss(context, {
        referencePress: true,
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
                            onMouseEnter: () => isInteractive && setIsHoveringTooltip(true),
                            onMouseLeave: () => isInteractive && setIsHoveringTooltip(false),
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

function TooltipBaseUI({
    children,
    title,
    className = '',
    placement = 'top',
    fallbackPlacements,
    offset = 8,
    arrowOffset,
    delayMs = 400,
    closeDelayMs = 0,
    interactive = false,
    visible: controlledOpen,
    docLink,
    containerClassName,
    onOpen,
}: React.PropsWithChildren<RequiredTooltipProps>): JSX.Element {
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const floatingContainer = useFloatingContainer()

    const open = controlledOpen ?? uncontrolledOpen

    useEffect(() => {
        if (open && onOpen) {
            onOpen()
        }
    }, [open, onOpen])

    const child = React.isValidElement(children) ? children : <span>{children}</span>

    if (!title && !docLink) {
        return <>{child}</>
    }

    const isInteractive = interactive || !!docLink
    const { side, align } = placementToSideAlign(placement)

    const collisionAvoidance = fallbackPlacements
        ? {
              side: 'flip' as const,
              align: 'flip' as const,
              fallbackAxisSide: 'start' as const,
          }
        : {
              side: 'flip' as const,
              align: 'shift' as const,
              fallbackAxisSide: 'start' as const,
          }

    const handleOpenChange = (newOpen: boolean): void => {
        if (controlledOpen === undefined) {
            setUncontrolledOpen(newOpen)
        }
    }

    return (
        <BaseTooltip.Root open={open} onOpenChange={handleOpenChange} disableHoverablePopup={!isInteractive}>
            <BaseTooltip.Trigger delay={delayMs} closeDelay={closeDelayMs} render={child} />
            <BaseTooltip.Portal container={floatingContainer}>
                <BaseTooltip.Positioner
                    side={side}
                    align={align}
                    sideOffset={offset}
                    arrowPadding={typeof arrowOffset === 'number' ? arrowOffset : 5}
                    collisionAvoidance={collisionAvoidance}
                    className={cn('Tooltip max-w-sm', containerClassName)}
                >
                    <BaseTooltip.Popup
                        className={cn(
                            'Tooltip__popup bg-surface-tooltip py-1.5 px-2 break-words rounded text-start',
                            className
                        )}
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
                        <BaseTooltip.Arrow className="Tooltip__arrow" />
                    </BaseTooltip.Popup>
                </BaseTooltip.Positioner>
            </BaseTooltip.Portal>
        </BaseTooltip.Root>
    )
}

export function Tooltip(props: React.PropsWithChildren<RequiredTooltipProps>): JSX.Element {
    const mountedFeatureFlagLogic = featureFlagLogic.findMounted()
    const { featureFlags } = mountedFeatureFlagLogic?.values || {}
    const useNewTooltip = !!featureFlags?.[FEATURE_FLAGS.UX_NEW_TOOLTIP]

    if (useNewTooltip) {
        return <TooltipBaseUI {...props} />
    }

    return <TooltipLegacy {...props} />
}

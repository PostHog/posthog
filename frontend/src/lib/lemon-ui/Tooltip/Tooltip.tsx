import './Tooltip.scss'

import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { Placement } from '@floating-ui/react'
import React, { useEffect, useLayoutEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { cn } from 'lib/utils/css-classes'

import { Link } from '../Link'

const DEFAULT_OFFSET = 8
// Smaller targets like the (I) info icon need a tighter gap so the user can
// reliably move from the trigger into the popup without losing hover.
const INFO_ICON_OFFSET = 4

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

function isInfoIconTrigger(node: React.ReactNode): boolean {
    if (!React.isValidElement(node)) {
        return false
    }
    if (node.type === IconInfo) {
        return true
    }
    const inner = (node.props as { children?: React.ReactNode } | null | undefined)?.children
    return React.isValidElement(inner) && inner.type === IconInfo
}

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

export function Tooltip({
    children,
    title,
    className = '',
    placement = 'top',
    fallbackPlacements,
    offset,
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
    const [shouldRenderPortal, setShouldRenderPortal] = useState(false)
    const floatingContainer = useFloatingContainer()

    const open = controlledOpen ?? uncontrolledOpen

    useLayoutEffect(() => {
        if (open) {
            setShouldRenderPortal(true)
        }
    }, [open])

    useEffect(() => {
        if (!open && shouldRenderPortal) {
            const timer = setTimeout(() => setShouldRenderPortal(false), 150)
            return () => clearTimeout(timer)
        }
    }, [open, shouldRenderPortal])

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
    const resolvedOffset = offset ?? (isInfoIconTrigger(children) ? INFO_ICON_OFFSET : DEFAULT_OFFSET)
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
            {shouldRenderPortal && (
                <BaseTooltip.Portal container={floatingContainer ?? undefined}>
                    <BaseTooltip.Positioner
                        side={side}
                        align={align}
                        sideOffset={resolvedOffset}
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
            )}
        </BaseTooltip.Root>
    )
}

import './Tooltip.scss'

import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { Placement } from '@floating-ui/react'
import React, { useEffect, useLayoutEffect, useState } from 'react'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
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
     * When true, the popup is part of the hoverable region so users can move the cursor into it
     * (e.g. to click an embedded link). Defaults to true when `docLink` is set or when `title` is
     * a non-string ReactNode (which may contain interactive content). Pass `false` to opt out.
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

export function Tooltip({
    children,
    title,
    className = '',
    placement = 'top',
    fallbackPlacements,
    offset = 8,
    arrowOffset,
    delayMs = 400,
    closeDelayMs,
    interactive,
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

    // A ReactNode title may render interactive content (e.g. a <Link>). Treat anything that isn't a
    // plain string or a function returning a string as potentially interactive so the popup stays
    // hoverable and the cursor can reach embedded links across the trigger/popup gap.
    const titleIsRichContent = title !== undefined && typeof title !== 'string' && typeof title !== 'function'
    const isInteractive = interactive ?? (!!docLink || titleIsRichContent)
    // When the popup is hoverable, give the cursor a grace period to traverse the offset gap before
    // the tooltip closes. Callers can still override explicitly.
    const effectiveCloseDelayMs = closeDelayMs ?? (isInteractive ? 200 : 0)
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
            <BaseTooltip.Trigger delay={delayMs} closeDelay={effectiveCloseDelayMs} render={child} />
            {shouldRenderPortal && (
                <BaseTooltip.Portal container={floatingContainer ?? undefined}>
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
            )}
        </BaseTooltip.Root>
    )
}

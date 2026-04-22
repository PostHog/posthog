import { Placement } from '@floating-ui/react'
import React from 'react'

// eslint-disable-next-line no-console
console.info('[memlens-stub] Tooltip stubbed — returns children only')

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
    interactive?: boolean
    docLink?: string
    onOpen?: () => void
}

export type RequiredTooltipProps = (
    | { title: TooltipTitle; docLink?: string }
    | { title?: TooltipTitle; docLink: string }
) &
    BaseTooltipProps

export function Tooltip({ children }: React.PropsWithChildren<RequiredTooltipProps>): JSX.Element {
    return <>{children}</>
}

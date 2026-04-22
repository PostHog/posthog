import { Middleware, Placement, UseFloatingReturn } from '@floating-ui/react'
import React, { MouseEventHandler } from 'react'

// eslint-disable-next-line no-console
console.info('[memlens-stub] Popover stubbed — renders children only, no overlay')

export interface PopoverProps {
    ref?: React.MutableRefObject<HTMLDivElement | null> | React.Ref<HTMLDivElement> | null
    visible: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    onMouseEnterInside?: MouseEventHandler<HTMLDivElement>
    onMouseLeaveInside?: MouseEventHandler<HTMLDivElement>
    children?: React.ReactNode
    referenceElement?: HTMLElement | null
    overlay: React.ReactNode | React.ReactNode[]
    placement?: Placement
    fallbackPlacements?: Placement[]
    loadingBar?: boolean
    actionable?: boolean
    matchWidth?: boolean
    maxContentWidth?: boolean
    className?: string
    padded?: boolean
    middleware?: Middleware[]
    additionalRefs?: React.MutableRefObject<HTMLDivElement | null>[]
    referenceRef?: UseFloatingReturn['refs']['reference']
    floatingRef?: UseFloatingReturn['refs']['floating']
    style?: React.CSSProperties
    overflowHidden?: boolean
    closeParentPopoverOnClickInside?: boolean
    showArrow?: boolean
    delayMs?: number
}

export const PopoverOverlayContext = React.createContext<[boolean, number]>([true, -1])
export const PopoverReferenceContext = React.createContext<[boolean, Placement] | null>(null)

export const Popover: React.ComponentType<PopoverProps> = function PopoverStub(props: PopoverProps): JSX.Element {
    return <>{props.children}</>
}

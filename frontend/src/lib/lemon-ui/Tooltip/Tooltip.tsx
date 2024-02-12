// import {
//     arrow,
//     autoUpdate,
//     flip,
//     FloatingArrow,
//     FloatingPortal,
//     offset as offsetFunc,
//     Placement,
//     shift,
//     useDismiss,
//     useFloating,
//     useFocus,
//     useHover,
//     useInteractions,
//     useMergeRefs,
//     useRole,
// } from '@floating-ui/react'
// import clsx from 'clsx'
// import React, { useRef, useState } from 'react'

// const DEFAULT_DELAY_MS = 500

// export type TooltipProps = {
//     title: string | React.ReactNode | (() => string)
//     children: JSX.Element
//     open?: boolean
//     delayMs?: number
//     offset?: number
//     placement?: Placement
//     className?: string
// }

// export function Tooltip({
//     title,
//     children,
//     open,
//     placement = 'top',
//     offset = 8,
//     delayMs = DEFAULT_DELAY_MS,
//     className = '',
// }: TooltipProps): JSX.Element {
//     const [isOpen, setIsOpen] = useState(false)
//     const caretRef = useRef(null)

//     const { refs, floatingStyles, context } = useFloating({
//         open: open === undefined ? isOpen : open,
//         onOpenChange: !open ? setIsOpen : undefined,
//         placement: placement,
//         whileElementsMounted: autoUpdate,
//         middleware: [
//             offsetFunc(offset),
//             flip({
//                 fallbackAxisSideDirection: 'start',
//             }),
//             shift(),
//             arrow({ element: caretRef }),
//         ],
//     })

//     const hover = useHover(context, { move: true, restMs: delayMs })
//     const focus = useFocus(context)
//     const dismiss = useDismiss(context)
//     const role = useRole(context, { role: 'tooltip' })
//     const { getReferenceProps, getFloatingProps } = useInteractions([hover, focus, dismiss, role])

//     // const child = React.isValidElement(children) ? children : <span>{children}</span>
//     // const childrenRef = (children as any).ref
//     const triggerRef = useMergeRefs([refs.setReference, (children as any).ref])

//     return title ? (
//         <>
//             {React.cloneElement(
//                 children,
//                 getReferenceProps({
//                     ref: triggerRef,
//                     ...children.props,
//                 })
//             )}
//             <FloatingPortal>
//                 {isOpen && (
//                     <>
//                         <div
//                             ref={refs.setFloating}
//                             className={clsx(
//                                 'bg-tooltip-bg py-1.5 px-2 z-[1070] break-words rounded text-start text-white',
//                                 className
//                             )}
//                             // eslint-disable-next-line react/forbid-dom-props
//                             style={floatingStyles}
//                             {...getFloatingProps()}
//                         >
//                             {typeof title === 'function' ? title() : title}
//                             <FloatingArrow ref={caretRef} context={context} fill="var(--tooltip-bg)" />
//                         </div>
//                     </>
//                 )}
//             </FloatingPortal>
//         </>
//     ) : (
//         children
//     )
// }

import type { Placement } from '@floating-ui/react'
import {
    autoUpdate,
    flip,
    FloatingPortal,
    offset as offsetFunc,
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
import * as React from 'react'
interface TooltipProps {
    title: string | React.ReactNode | (() => string)
    children: JSX.Element
    open?: boolean
    delayMs?: number
    offset?: number
    placement?: Placement
    className?: string
}

export function useTooltip({
    placement = 'top',
    offset = 8,
    delayMs = 500,
}: Omit<TooltipProps, 'title' | 'children' | 'className'>) {
    const [open, setOpen] = React.useState(false)

    const data = useFloating({
        placement,
        open,
        onOpenChange: setOpen,
        whileElementsMounted: autoUpdate,
        middleware: [
            offsetFunc(offset),
            flip({
                crossAxis: placement.includes('-'),
                fallbackAxisSideDirection: 'start',
                padding: 5,
            }),
            shift({ padding: 5 }),
        ],
    })

    const context = data.context

    const hover = useHover(context, {
        move: false,
    })
    const focus = useFocus(context)
    const dismiss = useDismiss(context)
    const role = useRole(context, { role: 'tooltip' })

    const interactions = useInteractions([hover, focus, dismiss, role])

    return React.useMemo(
        () => ({
            open,
            setOpen,
            ...interactions,
            ...data,
        }),
        [open, setOpen, interactions, data]
    )
}

type ContextType = ReturnType<typeof useTooltip> | null

const TooltipContext = React.createContext<ContextType>(null)

export const useTooltipContext = () => {
    const context = React.useContext(TooltipContext)

    if (context == null) {
        throw new Error('Tooltip components must be wrapped in <Tooltip />')
    }

    return context
}

export function Tooltip({ children, title, className, ...options }: TooltipProps) {
    const tooltip = useTooltip(options)

    return (
        <TooltipContext.Provider value={tooltip}>
            <TooltipTrigger>{children}</TooltipTrigger>
            <TooltipContent className={className}>{typeof title === 'function' ? title() : title}</TooltipContent>
        </TooltipContext.Provider>
    )
}

export const TooltipTrigger = React.forwardRef<HTMLElement, React.HTMLProps<HTMLElement>>(function TooltipTrigger(
    { children, ...props },
    propRef
) {
    const context = useTooltipContext()
    const childrenRef = (children as any).ref
    const ref = useMergeRefs([context.refs.setReference, propRef, childrenRef])

    const child = React.isValidElement(children) ? children : <span>{children}</span>

    return React.cloneElement(
        child,
        context.getReferenceProps({
            ref,
            ...props,
            ...child.props,
        })
    )
})

export const TooltipContent = React.forwardRef<HTMLDivElement, React.HTMLProps<HTMLDivElement>>(function TooltipContent(
    { className, ...props },
    propRef
) {
    const context = useTooltipContext()
    const ref = useMergeRefs([context.refs.setFloating, propRef])

    if (!context.open) {
        return null
    }

    return (
        <FloatingPortal>
            <div
                ref={ref}
                className={clsx(
                    'bg-tooltip-bg py-1.5 px-2 z-[1070] break-words rounded text-start text-white',
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ ...context.floatingStyles }}
                {...context.getFloatingProps(props)}
            />
        </FloatingPortal>
    )
})

import './Popup.scss'
import React, { MouseEventHandler, ReactElement, useEffect, useMemo } from 'react'
import ReactDOM from 'react-dom'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { offset, useFloating } from '@floating-ui/react-dom'
import clsx from 'clsx'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { CSSTransition } from 'react-transition-group'
import { flip, Middleware, Placement } from '@floating-ui/react-dom-interactions'

export interface PopupProps {
    visible?: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. */
    children: React.ReactChild | ((props: { setRef: (ref: HTMLElement | null) => void }) => JSX.Element)
    /** Content of the overlay. */
    overlay: React.ReactNode | React.ReactNode[]
    /** Where the popover should start relative to children. */
    placement?: Placement
    /** Where the popover should start relative to children if there's insufficient space for original placement. */
    fallbackPlacements?: Placement[]
    /** Whether the popover is actionable rather than just informative - actionable means a colored border. */
    actionable?: boolean
    /** Whether the popover's width should be synced with the children's width. */
    sameWidth?: boolean
    maxWindowDimensions?: boolean
    maxContentWidth?: boolean
    className?: string
    middleware?: Middleware[]
}

/** 0 means no parent. */
export const PopupContext = React.createContext<number>(0)

let uniqueMemoizedIndex = 1

// NOTE: copied from https://github.com/atomiks/popper-max-size-modifier/blob/370d0df2567d6083728eeeebff76cbeaf095ca1d/index.js
// const maxSizeModifier: Modifier<any, any> = {
//     name: 'maxSize',
//     enabled: true,
//     phase: 'main',
//     requiresIfExists: ['offset', 'preventOverflow', 'flip'],
//     fn({ state, name }) {
//         const overflow = detectOverflow(state)
//         const { x, y } = state.modifiersData.preventOverflow || { x: 0, y: 0 }
//         const { width, height } = state.rects.popper
//         const [basePlacement] = state.placement.split('-')
//
//         const widthProp = basePlacement === 'left' ? 'left' : 'right'
//         const heightProp = basePlacement === 'top' ? 'top' : 'bottom'
//
//         state.modifiersData[name] = {
//             width: width - overflow[widthProp] - x,
//             height: height - overflow[heightProp] - y,
//         }
//     },
// }

/** This is a custom popup control that uses `react-popper` to position DOM nodes.
 *
 * Often used with buttons for various menu. If this is your intention, use `LemonButtonWithPopup`.
 */
export function Popup({
    children,
    overlay,
    visible,
    onClickOutside,
    onClickInside,
    placement = 'bottom-start',
    fallbackPlacements = ['bottom-end', 'top-start', 'top-end'],
    className,
    actionable = false,
    sameWidth = false,
    middleware,
}: // maxContentWidth = false,
// maxWindowDimensions = false,
PopupProps): JSX.Element {
    useEffect(() => console.log('visible', visible), [visible])
    useEffect(() => console.log('placement', placement), [placement])

    const popupId = useMemo(() => uniqueMemoizedIndex++, [])
    useEffect(() => console.log('popupId', popupId), [popupId])

    const {
        x,
        y,
        reference,
        floating,
        refs: { reference: referenceRef, floating: floatingRef },
        strategy,
        update,
    } = useFloating({
        placement,
        middleware: [
            offset(4),
            ...(fallbackPlacements
                ? [
                      flip({
                          fallbackPlacements: fallbackPlacements,
                      }),
                  ]
                : []),
            // maxWindowDimensions ? maxSizeModifier : {},
            ...(sameWidth
                ? [
                      // {
                      //     name: 'sameWidth',
                      //     enabled: true,
                      //     fn: ({ state }) => {
                      //         state.styles.popper.width = `${state.rects.reference.width}px`
                      //     },
                      //     phase: 'beforeWrite',
                      //     requires: ['computeStyles'],
                      // },
                  ]
                : []),
            ...(middleware ?? []),
        ],
    })
    // console.log({ visible, popupId, x, y, strategy })
    useEffect(() => console.log('x', x), [x])
    useEffect(() => console.log('y', y), [y])
    useEffect(() => console.log('referenceRef', referenceRef.current), [referenceRef.current])
    useEffect(() => console.log('floatingRef', floatingRef.current), [floatingRef.current])
    useEffect(() => console.log('strategy', strategy), [strategy])

    useOutsideClickHandler([floatingRef, referenceRef], (event) => visible && onClickOutside?.(event), [visible])

    useResizeObserver({
        ref: floatingRef,
        onResize: () => update?.(), // When the element is resized, schedule a popper update to reposition
    })

    const clonedChildren =
        typeof children === 'function'
            ? children({ setRef: reference })
            : React.Children.toArray(children).map((child) =>
                  React.cloneElement(child as ReactElement, { ref: reference })
              )

    return (
        <>
            {clonedChildren}
            {ReactDOM.createPortal(
                <PopupContext.Provider value={popupId}>
                    <CSSTransition in={visible} timeout={100} classNames="Popup-" mountOnEnter unmountOnExit>
                        <div
                            className={clsx('Popup', actionable && 'Popup--actionable', className)}
                            ref={(ref) => {
                                debugger
                                ref && floating(ref)
                            }}
                            style={{ position: strategy, top: y ?? 0, left: x ?? 0 }}
                            onClick={onClickInside}
                        >
                            <div className="Popup__box">{overlay}</div>
                        </div>
                    </CSSTransition>
                </PopupContext.Provider>,
                document.querySelector('body') as HTMLElement
            )}
        </>
    )
}

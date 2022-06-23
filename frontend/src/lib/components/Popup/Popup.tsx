import './Popup.scss'
import React, { MouseEventHandler, MutableRefObject, ReactElement, useEffect, useMemo } from 'react'
import ReactDOM from 'react-dom'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import clsx from 'clsx'
import { CSSTransition } from 'react-transition-group'
import {
    offset,
    useFloating,
    autoUpdate,
    flip,
    Middleware,
    Placement,
    shift,
} from '@floating-ui/react-dom-interactions'

export interface PopupProps {
    visible?: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. */
    children:
        | React.ReactChild
        | ((props: {
              // setRef: (ref: HTMLElement | null) => void
              ref: MutableRefObject<HTMLElement | null>
          }) => JSX.Element)
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
// const sameWidthModifier = {
//     name: 'sameWidth',
//     enabled: true,
//     fn: ({ state }) => {
//         state.styles.popper.width = `${state.rects.reference.width}px`
//     },
//     phase: 'beforeWrite',
//     requires: ['computeStyles'],
// }

/** This is a custom popup control that uses `floating-ui` to position DOM nodes.
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
    fallbackPlacements = ['bottom-start', 'bottom-end', 'top-start', 'top-end'],
    className,
    actionable = false,
    middleware,
}: // sameWidth = false,
// maxWindowDimensions = false,
// maxContentWidth = false,
PopupProps): JSX.Element {
    const popupId = useMemo(() => uniqueMemoizedIndex++, [])
    const {
        x,
        y,
        // reference: setReferenceRef,
        floating: setFloatingRef,
        refs: { reference: referenceRef, floating: floatingRef },
        strategy,
        update,
    } = useFloating<HTMLElement>({
        placement,
        strategy: 'fixed',
        middleware: [
            offset(4),
            shift(),
            ...(fallbackPlacements ? [flip({ fallbackPlacements })] : []),
            // ...(maxWindowDimensions ? [maxSizeModifier] : []),
            // ...(sameWidth ? [sameWidthModifier] : []),
            ...(middleware ?? []),
        ],
    })

    useOutsideClickHandler([floatingRef, referenceRef], (event) => visible && onClickOutside?.(event), [visible])

    useEffect(() => {
        if (visible && referenceRef?.current && floatingRef?.current) {
            return autoUpdate(referenceRef.current, floatingRef.current, update)
        }
    }, [visible, referenceRef?.current, floatingRef?.current])

    const clonedChildren =
        typeof children === 'function'
            ? children({ ref: referenceRef })
            : React.Children.toArray(children).map((child) =>
                  React.cloneElement(child as ReactElement, { ref: referenceRef })
              )

    return (
        <>
            {clonedChildren}
            {ReactDOM.createPortal(
                <CSSTransition in={visible} timeout={100} classNames="Popup-" mountOnEnter unmountOnExit>
                    <PopupContext.Provider value={popupId}>
                        <div
                            className={clsx('Popup', actionable && 'Popup--actionable', className)}
                            ref={setFloatingRef}
                            style={{ position: strategy, top: y ?? 0, left: x ?? 0 }}
                            onClick={onClickInside}
                        >
                            <div className="Popup__box">{overlay}</div>
                        </div>
                    </PopupContext.Provider>
                </CSSTransition>,
                document.body
            )}
        </>
    )
}

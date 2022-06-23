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
    Middleware,
    Placement,
    shift,
    flip,
    size,
} from '@floating-ui/react-dom-interactions'

export interface PopupProps {
    visible?: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. If you pass one <Component/> child, it will get the `ref` prop automatically. */
    children: React.ReactChild | ((props: { ref: MutableRefObject<HTMLElement | null> }) => JSX.Element)
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
    maxContentWidth?: boolean
    className?: string
    middleware?: Middleware[]
}

/** 0 means no parent. */
export const PopupContext = React.createContext<number>(0)

let uniqueMemoizedIndex = 1

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
    sameWidth = false,
    maxContentWidth = false,
}: PopupProps): JSX.Element {
    const popupId = useMemo(() => uniqueMemoizedIndex++, [])
    const {
        x,
        y,
        refs: { reference: referenceRef, floating: floatingRef },
        strategy,
        placement: floatingPlacement,
        update,
    } = useFloating<HTMLElement>({
        placement,
        strategy: 'fixed',
        middleware: [
            offset(4),
            shift(),
            ...(fallbackPlacements ? [flip({ fallbackPlacements })] : []),
            size({
                padding: 5,
                apply({ rects, availableHeight, elements: { floating } }) {
                    if (sameWidth) {
                        Object.assign(floating.style, {
                            width: `${rects.reference.width}px`,
                        })
                    }
                    Object.assign(floating.style, {
                        maxHeight: `${Math.max(50, availableHeight)}px`,
                    })
                },
            }),
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
                            className={clsx(
                                'Popup',
                                actionable && 'Popup--actionable',
                                maxContentWidth && 'Popup--max-content-width',
                                className
                            )}
                            data-floating-placement={floatingPlacement}
                            ref={floatingRef as MutableRefObject<HTMLDivElement>}
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

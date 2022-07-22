import './Popup.scss'
import React, {
    MouseEventHandler,
    MutableRefObject,
    ReactElement,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'
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
    arrow,
} from '@floating-ui/react-dom-interactions'

export interface PopupProps {
    ref?: React.MutableRefObject<HTMLDivElement | null>
    visible?: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. If you pass one <Component/> child, it will get the `ref` prop automatically. */
    children?: React.ReactChild | ((props: { ref: MutableRefObject<HTMLElement | null> }) => JSX.Element)
    /** External reference element not passed as a direct child */
    referenceElement?: HTMLElement
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
    /** Any other refs that needs to be taken into account for handling outside clicks e.g. other nested popups.
     * Works also with strings, matching classnames or ids, for antd legacy components that don't support refs
     * **/
    additionalRefs?: (React.MutableRefObject<HTMLDivElement | null> | string)[]
    style?: React.CSSProperties
    getPopupContainer?: () => HTMLElement
    /** Whether to show an arrow pointing to a reference element */
    showArrow?: boolean
}

/** 0 means no parent. */
export const PopupContext = React.createContext<number>(0)

let uniqueMemoizedIndex = 1

/** This is a custom popup control that uses `floating-ui` to position DOM nodes.
 *
 * Often used with buttons for various menu. If this is your intention, use `LemonButtonWithPopup`.
 */
export const Popup = React.forwardRef<HTMLDivElement, PopupProps>(
    (
        {
            children,
            referenceElement,
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
            additionalRefs = [],
            style,
            getPopupContainer,
            showArrow,
        },
        ref
    ): JSX.Element => {
        const popupId = useMemo(() => uniqueMemoizedIndex++, [])
        const arrowRef = useRef<HTMLDivElement>(null)
        const {
            x,
            y,
            reference,
            refs: { reference: referenceRef, floating: floatingRef },
            strategy,
            placement: floatingPlacement,
            update,
            middlewareData,
        } = useFloating<HTMLElement>({
            placement,
            strategy: 'fixed',
            middleware: [
                offset(4),
                ...(fallbackPlacements ? [flip({ fallbackPlacements })] : []),
                shift(),
                size({
                    padding: 5,
                    apply({ rects, elements: { floating } }) {
                        if (sameWidth) {
                            Object.assign(floating.style, {
                                width: `${rects.reference.width}px`,
                            })
                        }
                    },
                }),
                arrow({ element: arrowRef }),
                ...(middleware ?? []),
            ],
        })

        const arrowStaticSide = {
            top: 'bottom',
            right: 'left',
            bottom: 'top',
            left: 'right',
        }[floatingPlacement.split('-')[0]] as string

        const arrowStyle = middlewareData.arrow
            ? {
                  left: `${middlewareData.arrow.x}px`,
                  top: `${middlewareData.arrow.y}px`,
                  [arrowStaticSide]: '-0.25rem',
              }
            : {}

        useLayoutEffect(() => {
            if (referenceElement) {
                reference(referenceElement)
            }
        }, [referenceElement])

        useOutsideClickHandler(
            [floatingRef, referenceRef, ...additionalRefs],
            (event) => visible && onClickOutside?.(event),
            [visible]
        )

        useEffect(() => {
            if (visible && referenceRef?.current && floatingRef?.current) {
                return autoUpdate(referenceRef.current, floatingRef.current, update)
            }
        }, [visible, referenceRef?.current, floatingRef?.current, ...additionalRefs])

        const clonedChildren = children
            ? typeof children === 'function'
                ? children({ ref: referenceRef })
                : React.Children.toArray(children).map((child) =>
                      React.cloneElement(child as ReactElement, { ref: referenceRef })
                  )
            : null

        const isAttached = clonedChildren || referenceElement
        const top = isAttached ? y ?? 0 : undefined
        const left = isAttached ? x ?? 0 : undefined

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
                                    !isAttached && 'Popup--top-centered',
                                    className
                                )}
                                data-floating-placement={floatingPlacement}
                                ref={floatingRef as MutableRefObject<HTMLDivElement>}
                                style={{ position: strategy, top, left, ...style }}
                                onClick={onClickInside}
                            >
                                <div ref={ref} className="Popup__box">
                                    {overlay}
                                </div>
                                {showArrow && isAttached && (
                                    <div
                                        ref={arrowRef}
                                        className={clsx(
                                            'Popup__arrow',
                                            `Popup__arrow--${arrowStaticSide}`,
                                            actionable && 'Popup--actionable'
                                        )}
                                        style={arrowStyle}
                                    />
                                )}
                            </div>
                        </PopupContext.Provider>
                    </CSSTransition>,
                    getPopupContainer ? getPopupContainer() : document.body
                )}
            </>
        )
    }
)

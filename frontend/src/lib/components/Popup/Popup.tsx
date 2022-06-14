import './Popup.scss'
import React, { MouseEventHandler, ReactElement, useMemo, useState } from 'react'
import ReactDOM from 'react-dom'
import { usePopper } from 'react-popper'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { Modifier, Placement, detectOverflow } from '@popperjs/core'
import clsx from 'clsx'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { CSSTransition } from 'react-transition-group'

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
    className?: string
    modifier?: Record<string, any>
}

/** 0 means no parent. */
export const PopupContext = React.createContext<number>(0)

let uniqueMemoizedIndex = 1

// NOTE: copied from https://github.com/atomiks/popper-max-size-modifier/blob/370d0df2567d6083728eeeebff76cbeaf095ca1d/index.js
const maxSizeModifier: Modifier<any, any> = {
    name: 'maxSize',
    enabled: true,
    phase: 'main',
    requiresIfExists: ['offset', 'preventOverflow', 'flip'],
    fn({ state, name }) {
        const overflow = detectOverflow(state)
        const { x, y } = state.modifiersData.preventOverflow || { x: 0, y: 0 }
        const { width, height } = state.rects.popper
        const [basePlacement] = state.placement.split('-')

        const widthProp = basePlacement === 'left' ? 'left' : 'right'
        const heightProp = basePlacement === 'top' ? 'top' : 'bottom'

        state.modifiersData[name] = {
            width: width - overflow[widthProp] - x,
            height: height - overflow[heightProp] - y,
        }
    },
}

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
    modifier = {},
}: PopupProps): JSX.Element {
    const [referenceElement, setReferenceElement] = useState<HTMLDivElement | null>(null)
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)

    const popupId = useMemo(() => uniqueMemoizedIndex++, [])
    const localRefs = [popperElement, referenceElement]

    useOutsideClickHandler(localRefs, (event) => visible && onClickOutside?.(event), [visible])

    const modifiers = useMemo<Partial<Modifier<any, any>>[]>(
        () => [
            {
                name: 'offset',
                options: {
                    offset: [0, 4],
                },
            },
            maxSizeModifier,
            fallbackPlacements
                ? {
                      name: 'flip',
                      options: {
                          fallbackPlacements: fallbackPlacements,
                      },
                  }
                : {},
            sameWidth
                ? {
                      name: 'sameWidth',
                      enabled: true,
                      fn: ({ state }) => {
                          state.styles.popper.width = `${state.rects.reference.width}px`
                      },
                      phase: 'beforeWrite',
                      requires: ['computeStyles'],
                  }
                : {},
            modifier,
        ],
        []
    )

    const { styles, attributes, update, state } = usePopper(referenceElement, popperElement, {
        placement: placement,
        modifiers,
    })
    useResizeObserver({
        ref: popperElement,
        onResize: () => update?.(), // When the element is resized, schedule a popper update to reposition
    })

    const clonedChildren =
        typeof children === 'function'
            ? children({
                  setRef: setReferenceElement as (ref: HTMLElement | null) => void,
              })
            : React.Children.toArray(children).map((child) =>
                  React.cloneElement(child as ReactElement, {
                      ref: setReferenceElement,
                  })
              )

    return (
        <>
            {clonedChildren}
            {ReactDOM.createPortal(
                <CSSTransition in={visible} timeout={100} classNames="Popup-" mountOnEnter unmountOnExit>
                    <div
                        className={clsx('Popup', actionable && 'Popup--actionable', className)}
                        ref={setPopperElement}
                        style={styles.popper}
                        onClick={onClickInside}
                        {...attributes.popper}
                    >
                        <div
                            className="Popup__box"
                            style={{
                                maxWidth: state?.modifiersData?.maxSize?.width,
                                maxHeight: state?.modifiersData?.maxSize?.height,
                            }}
                        >
                            <PopupContext.Provider value={popupId}>{overlay}</PopupContext.Provider>
                        </div>
                    </div>
                </CSSTransition>,
                document.querySelector('body') as HTMLElement
            )}
        </>
    )
}

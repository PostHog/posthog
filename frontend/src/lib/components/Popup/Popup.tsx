import './Popup.scss'
import React, { MouseEventHandler, ReactElement, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import ReactDOM from 'react-dom'
import { usePopper } from 'react-popper'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { Modifier, Placement } from '@popperjs/core'
import clsx from 'clsx'

export interface PopupProps {
    visible?: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. */
    children: React.ReactChild | ((props: { setRef: (ref: HTMLElement | null) => void }) => JSX.Element)
    /** Content of the overlay. */
    overlay: React.ReactNode
    /** Where the popover should start relative to children. */
    placement?: Placement
    /** Where the popover should start relative to children if there's insufficient space for original placement. */
    fallbackPlacements?: Placement[]
    /** Whether the popover is actionable rather than just informative - actionable means a colored border. */
    actionable?: boolean
    /** Whether the popover's width should be synced with the children's width. */
    sameWidth?: boolean
    className?: string
}

const PopupContext = React.createContext<number>(0)
const disabledPopups = new Map<number, number>()
let uniqueMemoizedIndex = 0

/** This is a custom popup control that uses `react-popper` to position DOM nodes */
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
}: PopupProps): JSX.Element {
    const parentPopupId = useContext(PopupContext)

    const [referenceElement, setReferenceElement] = useState<HTMLDivElement | null>(null)
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)

    const popupId = useMemo(() => ++uniqueMemoizedIndex, [])
    const localRefs = [popperElement, referenceElement]

    useEffect(() => {
        if (visible) {
            disabledPopups.set(popupId, parentPopupId)
            return () => {
                disabledPopups.delete(popupId)
            }
        }
    }, [visible, parentPopupId])

    useOutsideClickHandler(
        localRefs,
        (event) => {
            if (visible) {
                onClickOutside?.(event)
            }
        },
        [visible, disabledPopups]
    )

    const onClickInsideConditional = useCallback(
        (event) => {
            // Don't run onClickInside if this popup is a child of another popup
            console.log('clicked', disabledPopups, parentPopupId, popupId)
            if (!disabledPopups.has(popupId)) {
                onClickInside?.(event)
            }
        },
        [visible, disabledPopups]
    )

    const modifiers = useMemo<Partial<Modifier<any, any>>[]>(
        () => [
            {
                name: 'offset',
                options: {
                    offset: [0, 4],
                },
            },
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
        ],
        []
    )

    const { styles, attributes } = usePopper(referenceElement, popperElement, {
        placement: placement,
        modifiers,
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
            {visible
                ? ReactDOM.createPortal(
                      <div
                          className={clsx('Popup', actionable && 'Popup--actionable', className)}
                          ref={setPopperElement}
                          style={styles.popper}
                          onClick={onClickInsideConditional}
                          {...attributes.popper}
                      >
                          <PopupContext.Provider value={popupId}>{overlay}</PopupContext.Provider>
                      </div>,
                      document.querySelector('body') as HTMLElement
                  )
                : null}
        </>
    )
}

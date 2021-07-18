import './Popup.scss'
import React, { ReactElement, useState } from 'react'
import { usePopper } from 'react-popper'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { Placement } from '@popperjs/core'

interface PopupProps {
    visible?: boolean
    onClickOutside?: () => void
    children: React.ReactChild | ((props: { setRef?: (ref: HTMLElement) => void }) => JSX.Element)
    overlay: React.ReactNode
    placement?: Placement
    fallbackPlacements?: Placement[]
}

export function Popup({
    children,
    overlay,
    visible,
    onClickOutside,
    placement = 'bottom-start',
    fallbackPlacements = ['bottom-end', 'top-start', 'top-end'],
}: PopupProps): JSX.Element {
    const [referenceElement, setReferenceElement] = useState<HTMLDivElement | null>(null)
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)
    const [arrowElement, setArrowElement] = useState<HTMLDivElement | null>(null)
    useOutsideClickHandler([popperElement, referenceElement, arrowElement] as HTMLElement[], onClickOutside)

    const { styles, attributes } = usePopper(referenceElement, popperElement, {
        placement: placement,
        modifiers: [
            { name: 'arrow', options: { element: arrowElement } },
            fallbackPlacements
                ? {
                      name: 'flip',
                      options: {
                          fallbackPlacements: fallbackPlacements,
                      },
                  }
                : {},
        ],
    })

    const clonedChildren =
        typeof children === 'function'
            ? children({
                  setRef: setReferenceElement as (ref: HTMLElement) => void,
              })
            : React.Children.toArray(children).map((child) =>
                  React.cloneElement(child as ReactElement, {
                      ref: setReferenceElement,
                  })
              )

    return (
        <>
            {clonedChildren}
            {visible && (
                <div className="popper-tooltip" ref={setPopperElement} style={styles.popper} {...attributes.popper}>
                    {overlay}
                    <div ref={setArrowElement} style={styles.arrow} />
                </div>
            )}
        </>
    )
}

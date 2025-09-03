import './Popover.scss'

import {
    FloatingPortal,
    Middleware,
    Placement,
    UseFloatingReturn,
    arrow,
    autoUpdate,
    flip,
    shift,
    size,
    useFloating,
    useMergeRefs,
} from '@floating-ui/react'
import clsx from 'clsx'
import React, { MouseEventHandler, ReactElement, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { CSSTransition } from 'react-transition-group'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { CLICK_OUTSIDE_BLOCK_CLASS, useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

import { LemonTableLoader } from '../LemonTable/LemonTableLoader'

export interface PopoverProps {
    ref?: React.MutableRefObject<HTMLDivElement | null> | React.Ref<HTMLDivElement> | null
    visible: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    onMouseEnterInside?: MouseEventHandler<HTMLDivElement>
    onMouseLeaveInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. If you pass one <Component/> child, it will get the `ref` prop automatically. */
    children?: React.ReactNode
    /** External reference element not passed as a direct child */
    referenceElement?: HTMLElement | null
    /** Content of the overlay. */
    overlay: React.ReactNode | React.ReactNode[]
    /** Where the popover should start relative to children. */
    placement?: Placement
    /** Where the popover should start relative to children if there's insufficient space for original placement. */
    fallbackPlacements?: Placement[]
    /**
     * Whether to show a loading bar at the top of the overlay.
     * DON'T ENABLE WHEN USING SKELETON CONTENT! Having both a skeleton AND loading bar is too much.
     * Note: for (dis)appearance of the bar to be smooth, you should flip between false/true, and not undefined/true.
     */
    loadingBar?: boolean
    /** @deprecated */
    actionable?: boolean
    /** Whether the popover's width should be synced with the children's width or bigger. */
    matchWidth?: boolean
    maxContentWidth?: boolean
    className?: string
    /** Whether default box padding should be applies. @default true */
    padded?: boolean
    middleware?: Middleware[]
    /** Any other refs that needs to be taken into account for handling outside clicks e.g. other nested popovers. */
    additionalRefs?: React.MutableRefObject<HTMLDivElement | null>[]
    referenceRef?: UseFloatingReturn['refs']['reference']
    floatingRef?: UseFloatingReturn['refs']['floating']
    style?: React.CSSProperties
    overflowHidden?: boolean
    /**
     * Whether the parent popover should be closed as well on click. Useful for menus.
     *  @default false
     */
    closeParentPopoverOnClickInside?: boolean
    /** Whether to show an arrow pointing to a reference element */
    showArrow?: boolean
    /** An added delay before the floating overlay is shown */
    delayMs?: number
}

/** Context for the popover overlay: parent popover visibility and parent popover level. */
export const PopoverOverlayContext = React.createContext<[boolean, number]>([true, -1])
/** Context for the popover reference element (if it's rendered as a Popover child and not externally). */
export const PopoverReferenceContext = React.createContext<[boolean, Placement] | null>(null)

let nestedPopoverReceivedClick = false

/** This is a custom popover control that uses `floating-ui` to position DOM nodes.
 *
 * Often used with buttons for various menu. If this is your intention, use `LemonButtonWithDropdown`.
 */
export const Popover = React.forwardRef<HTMLDivElement, PopoverProps>(function PopoverInternal(
    {
        children,
        referenceElement,
        overlay,
        loadingBar,
        visible,
        onClickOutside,
        onClickInside,
        onMouseEnterInside,
        onMouseLeaveInside,
        placement = 'bottom-start',
        fallbackPlacements = ['top-start', 'top-end', 'bottom-start', 'bottom-end'],
        className,
        padded = true,
        middleware,
        matchWidth = false,
        maxContentWidth = false,
        additionalRefs = [],
        closeParentPopoverOnClickInside = false,
        referenceRef: extraReferenceRef,
        floatingRef: extraFloatingRef,
        style,
        showArrow = false,
        overflowHidden = false,
        delayMs = 50,
    },
    contentRef
): JSX.Element {
    const [parentPopoverVisible, parentPopoverLevel] = useContext(PopoverOverlayContext)
    const currentPopoverLevel = parentPopoverLevel + 1

    if (!parentPopoverVisible) {
        // If parentPopoverVisible is false, this means the parent will be unmounted imminently (per CSSTransition),
        // and then THIS child popover wil also be unmounted. Here we propagate this transition from the parent,
        // so that all of the unmounting seems smooth and not abrupt (which is how it'd look for this child otherwise)
        visible = false
    }

    const arrowRef = useRef<HTMLDivElement>(null)
    const {
        x,
        y,
        refs: { reference: referenceRef, floating: floatingRef, setReference },
        strategy,
        placement: effectivePlacement,
        update,
        middlewareData,
    } = useFloating<HTMLElement>({
        open: visible,
        placement,
        strategy: 'absolute',
        middleware: [
            ...(fallbackPlacements
                ? [
                      flip({
                          fallbackPlacements: [
                              // Prioritize top placements when there might be space issues
                              ...fallbackPlacements.filter((p) => p.startsWith('top')),
                              ...fallbackPlacements.filter((p) => !p.startsWith('top')),
                          ],
                          fallbackStrategy: 'bestFit',
                          padding: { bottom: 150 }, // Require at least 150px of space below to avoid flipping
                      }),
                  ]
                : []),
            shift({ padding: 8, boundary: document.body }), // Add padding and use document.body as boundary
            size({
                padding: 4,
                apply({ availableWidth, availableHeight, rects, elements: { floating } }) {
                    const minHeight = 200 // Minimum desired height

                    // If there's insufficient height, set a reasonable max height but still allow content to be scrollable
                    if (availableHeight < minHeight) {
                        floating.style.maxHeight = `${Math.max(availableHeight, 150)}px`
                    } else {
                        floating.style.maxHeight = `${availableHeight}px`
                    }

                    floating.style.maxWidth = `${Math.min(availableWidth, window.innerWidth - 16)}px` // Ensure popover doesn't extend past window edge
                    floating.style.width = 'initial'
                    if (matchWidth) {
                        floating.style.minWidth = `${rects.reference.width}px`
                    }
                },
            }),
            ...(showArrow ? [arrow({ element: arrowRef, padding: 8 })] : []),
            ...(middleware ?? []),
        ],
    })

    const [floatingElement, setFloatingElement] = useState<HTMLElement | null>(null)
    const mergedReferenceRef = useMergeRefs([
        referenceRef,
        extraReferenceRef || null,
        (children as any)?.ref,
    ]) as React.RefCallback<HTMLElement>

    const arrowStyle = middlewareData.arrow
        ? {
              left: `${middlewareData.arrow.x}px`,
              top: `${middlewareData.arrow.y}px`,
          }
        : {}

    useLayoutEffect(() => {
        if (referenceElement) {
            setReference(referenceElement)
        }
    }, [referenceElement]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEventListener(
        'keydown',
        (event) => {
            if (event.key === 'Escape') {
                onClickOutside?.(event as Event)
            }
        },
        referenceElement
    )

    useOutsideClickHandler(
        [floatingRef, referenceRef, ...additionalRefs],
        (event) => {
            // Delay by a tick to allow other Popovers to detect inside clicks.
            // If a nested popover has handled the click, don't do anything
            setTimeout(() => {
                if (visible && !nestedPopoverReceivedClick) {
                    onClickOutside?.(event)
                }
            }, 1)
        },
        [visible]
    )

    useEffect(() => {
        if (visible && referenceRef?.current && floatingElement) {
            return autoUpdate(referenceRef.current, floatingElement, update)
        }
    }, [visible, placement, referenceRef?.current, floatingElement, ...additionalRefs]) // oxlint-disable-line react-hooks/exhaustive-deps

    const floatingContainer = useFloatingContainer()

    const _onClickInside: MouseEventHandler<HTMLDivElement> = (e): void => {
        if (e.target instanceof HTMLElement && e.target.closest(`.${CLICK_OUTSIDE_BLOCK_CLASS}`)) {
            return
        }
        onClickInside?.(e)
        // If we are not the top level popover, set a flag so that other popovers know that.
        if (parentPopoverLevel > -1 && !closeParentPopoverOnClickInside) {
            nestedPopoverReceivedClick = true
            setTimeout(() => {
                nestedPopoverReceivedClick = false
            }, 1)
        }
    }

    const clonedChildren = children ? React.cloneElement(children as ReactElement, { ref: mergedReferenceRef }) : null

    const isAttached = clonedChildren || referenceElement
    const top = isAttached ? (y ?? 0) : undefined
    const left = isAttached ? (x ?? 0) : undefined

    return (
        <>
            {clonedChildren && (
                <PopoverReferenceContext.Provider value={[visible, effectivePlacement]}>
                    {clonedChildren}
                </PopoverReferenceContext.Provider>
            )}
            {visible ? (
                <FloatingPortal root={floatingContainer}>
                    <CSSTransition
                        in={visible}
                        timeout={delayMs}
                        classNames="Popover-"
                        appear
                        mountOnEnter
                        unmountOnExit
                    >
                        <PopoverReferenceContext.Provider
                            value={null /* Resetting the reference, since there's none */}
                        >
                            <PopoverOverlayContext.Provider value={[visible, currentPopoverLevel]}>
                                <div
                                    className={clsx(
                                        'Popover',
                                        padded && 'Popover--padded',
                                        maxContentWidth && 'Popover--max-content-width',
                                        !isAttached && 'Popover--top-centered',
                                        showArrow && 'Popover--with-arrow',
                                        className
                                    )}
                                    data-placement={effectivePlacement}
                                    ref={(el) => {
                                        setFloatingElement(el)
                                        floatingRef.current = el
                                        if (extraFloatingRef) {
                                            extraFloatingRef.current = el
                                        }
                                    }}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        display: middlewareData.hide?.referenceHidden ? 'none' : undefined,
                                        position: strategy,
                                        top,
                                        left,
                                        ...style,
                                    }}
                                    onClick={_onClickInside}
                                    onMouseEnter={onMouseEnterInside}
                                    onMouseLeave={onMouseLeaveInside}
                                    aria-level={currentPopoverLevel}
                                >
                                    <div className="Popover__box">
                                        {showArrow && isAttached && (
                                            // Arrow is outside of .Popover__content to avoid affecting :nth-child for content
                                            <div
                                                ref={arrowRef}
                                                className="Popover__arrow"
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={arrowStyle}
                                            />
                                        )}

                                        {loadingBar != null && (
                                            <LemonTableLoader loading={loadingBar} placement="top" />
                                        )}

                                        {!overflowHidden ? (
                                            <ScrollableShadows
                                                className="Popover__content"
                                                ref={contentRef}
                                                direction="vertical"
                                            >
                                                {overlay}
                                            </ScrollableShadows>
                                        ) : (
                                            <div
                                                className="Popover__content flex flex-col overflow-hidden"
                                                ref={contentRef}
                                            >
                                                {overlay}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </PopoverOverlayContext.Provider>
                        </PopoverReferenceContext.Provider>
                    </CSSTransition>
                </FloatingPortal>
            ) : null}
        </>
    )
})

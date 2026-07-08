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
    useDismiss,
    useFloating,
    useInteractions,
    useMergeRefs,
} from '@floating-ui/react'
import clsx from 'clsx'
import React, {
    MouseEventHandler,
    ReactElement,
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

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

// Registry of currently-visible Popover floating elements with their nesting level.
// Used so a parent popover doesn't treat a click on a deeper-nested popover as an outside click.
const openPopoverFloatings: Array<{ level: number; element: HTMLElement }> = []

// Whether a click target opted out of outside-dismiss via CLICK_OUTSIDE_BLOCK_CLASS. Mirrors the
// global exemption the legacy useOutsideClickHandler already applies, so both outside-click paths
// agree. `Element` (not `HTMLElement`) so a click landing on an SVG icon inside an opted-out
// element still matches.
const optedOutOfOutsideDismiss = (target: EventTarget | Node | null): boolean =>
    target instanceof Element && !!target.closest(`.${CLICK_OUTSIDE_BLOCK_CLASS}`)

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
        // If parentPopoverVisible is false, this means the parent will unmount imminently
        // (per its own exit timeout), and then THIS child popover will also be unmounted.
        // Propagate the transition from the parent so that all of the unmounting seems
        // smooth and not abrupt (which is how it'd look for this child otherwise).
        visible = false
    }

    const arrowRef = useRef<HTMLDivElement>(null)
    const additionalRefsRef = useRef(additionalRefs)
    additionalRefsRef.current = additionalRefs

    const {
        x,
        y,
        refs: { reference: referenceRef, floating: floatingRef, setReference },
        strategy,
        placement: effectivePlacement,
        update,
        middlewareData,
        context,
    } = useFloating<HTMLElement>({
        open: visible,
        onOpenChange: (open, event) => {
            if (open || !visible || !event) {
                return
            }
            onClickOutside?.(event as Event)
        },
        placement,
        strategy: 'absolute',
        middleware: [
            ...(fallbackPlacements
                ? [
                      flip({
                          fallbackPlacements,
                          fallbackStrategy: 'bestFit',
                          padding: 20,
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
    // `shouldRenderPortal` controls whether the portal is mounted. It flips to
    // `true` as soon as `visible` becomes true and flips back to `false` after
    // the exit transition has had `delayMs` to play out — this matches the
    // behaviour of the previous `CSSTransition` + `unmountOnExit` setup.
    // `isOpen` controls the CSS open/close class toggle that drives the
    // fade-in/fade-out transition defined in Popover.scss.
    const [shouldRenderPortal, setShouldRenderPortal] = useState(false)
    const [isOpen, setIsOpen] = useState(false)
    const exitTimeoutRef = useRef<number | null>(null)
    const enterFrameRef = useRef<number | null>(null)

    useLayoutEffect(() => {
        if (visible) {
            if (exitTimeoutRef.current !== null) {
                clearTimeout(exitTimeoutRef.current)
                exitTimeoutRef.current = null
            }
            setShouldRenderPortal(true)
            // Wait one animation frame before applying the `open` class so the
            // initial (closed) styles commit first and the transition plays.
            enterFrameRef.current = requestAnimationFrame(() => {
                enterFrameRef.current = null
                setIsOpen(true)
            })
        } else {
            if (enterFrameRef.current !== null) {
                cancelAnimationFrame(enterFrameRef.current)
                enterFrameRef.current = null
            }
            if (exitTimeoutRef.current !== null) {
                // Covers the case where `delayMs` changes while `visible` is already
                // false: without this, the previous timer would be orphaned rather
                // than cancelled.
                clearTimeout(exitTimeoutRef.current)
                exitTimeoutRef.current = null
            }
            setIsOpen(false)
            exitTimeoutRef.current = window.setTimeout(() => {
                exitTimeoutRef.current = null
                setFloatingElement(null)
                floatingRef.current = null
                if (extraFloatingRef) {
                    extraFloatingRef.current = null
                }
                setShouldRenderPortal(false)
            }, delayMs)
        }
    }, [visible, delayMs]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(
        () => () => {
            if (exitTimeoutRef.current !== null) {
                clearTimeout(exitTimeoutRef.current)
            }
            if (enterFrameRef.current !== null) {
                cancelAnimationFrame(enterFrameRef.current)
            }
        },
        []
    )
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

    const dismiss = useDismiss(context, {
        enabled: visible,
        // useDismiss only treats the floating + reference elements as "inside". Three things
        // need explicit exemption: elements opting out via CLICK_OUTSIDE_BLOCK_CLASS,
        // additionalRefs (consumer-registered companion elements), and deeper-nested popovers
        // (portaled, so DOM-siblings rather than descendants).
        outsidePress: (event) => {
            const target = event.target as Node | null
            if (!target) {
                return true
            }
            // Honor the block class on the floating-ui dismiss path too, not just onClickInside —
            // a nested menu in a parent popover's *reference* subtree (e.g. the TaxonomicFilter
            // category pill in the search input's suffix) inherits the wrong overlay level, so the
            // level check below can't recognize it as nested.
            if (optedOutOfOutsideDismiss(target)) {
                return false
            }
            if (additionalRefsRef.current.some((r) => r.current?.contains(target))) {
                return false
            }
            return !openPopoverFloatings.some((p) => p.level > currentPopoverLevel && p.element.contains(target))
        },
    })
    const { getFloatingProps } = useInteractions([dismiss])

    useEffect(() => {
        // When closeParentPopoverOnClickInside is set, this popover deliberately presents itself
        // as "outside" to its parent so parent menus dismiss on item click — skip registration.
        if (!visible || !floatingElement || closeParentPopoverOnClickInside) {
            return
        }
        const entry = { level: currentPopoverLevel, element: floatingElement }
        openPopoverFloatings.push(entry)
        return () => {
            const i = openPopoverFloatings.indexOf(entry)
            if (i >= 0) {
                openPopoverFloatings.splice(i, 1)
            }
        }
    }, [visible, floatingElement, currentPopoverLevel, closeParentPopoverOnClickInside])

    useEffect(() => {
        if (visible && referenceRef?.current && floatingElement) {
            return autoUpdate(referenceRef.current, floatingElement, update)
        }
    }, [visible, placement, referenceRef?.current, floatingElement]) // oxlint-disable-line react-hooks/exhaustive-deps

    const floatingContainer = useFloatingContainer()

    useEffect(() => {
        return () => {
            floatingRef.current = null
            if (extraFloatingRef) {
                extraFloatingRef.current = null
            }
        }
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    const _onClickInside: MouseEventHandler<HTMLDivElement> = (e): void => {
        if (optedOutOfOutsideDismiss(e.target)) {
            return
        }
        onClickInside?.(e)
    }

    const clonedChildren = children ? React.cloneElement(children as ReactElement, { ref: mergedReferenceRef }) : null

    const floatingCallbackRef = useCallback(
        (el: HTMLDivElement | null) => {
            setFloatingElement(el)
            floatingRef.current = el
            if (extraFloatingRef) {
                extraFloatingRef.current = el
            }
        },
        [setFloatingElement, floatingRef, extraFloatingRef]
    )

    const isAttached = clonedChildren || referenceElement
    const top = isAttached ? (y ?? 0) : undefined
    const left = isAttached ? (x ?? 0) : undefined
    // When attached to a reference, floating-ui needs at least one update cycle to compute
    // x/y. Until then, rendering at the (0, 0) fallback would briefly flash the overlay at
    // the top-left of the viewport. Hide it until positioning resolves.
    const isPositionPending = isAttached && (x == null || y == null)

    return (
        <>
            {clonedChildren && (
                <PopoverReferenceContext.Provider value={[visible, effectivePlacement]}>
                    {clonedChildren}
                </PopoverReferenceContext.Provider>
            )}
            {shouldRenderPortal && (
                // floating-ui@0.27 changed null to suppress the portal entirely
                <FloatingPortal root={floatingContainer ?? undefined}>
                    <PopoverReferenceContext.Provider value={null /* Resetting the reference, since there's none */}>
                        <PopoverOverlayContext.Provider value={[visible, currentPopoverLevel]}>
                            <div
                                className={clsx(
                                    'Popover',
                                    padded && 'Popover--padded',
                                    maxContentWidth && 'Popover--max-content-width',
                                    !isAttached && 'Popover--top-centered',
                                    showArrow && 'Popover--with-arrow',
                                    isOpen && 'Popover--enter-active',
                                    className
                                )}
                                data-placement={effectivePlacement}
                                ref={floatingCallbackRef}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    display:
                                        middlewareData.hide?.referenceHidden || isPositionPending ? 'none' : undefined,
                                    position: strategy,
                                    top,
                                    left,
                                    ...style,
                                }}
                                {...getFloatingProps({
                                    onClick: _onClickInside,
                                })}
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

                                    {loadingBar != null && <LemonTableLoader loading={loadingBar} placement="top" />}

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
                </FloatingPortal>
            )}
        </>
    )
})

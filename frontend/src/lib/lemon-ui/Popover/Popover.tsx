import './Popover.scss'
import React, { MouseEventHandler, ReactElement, useContext, useEffect, useLayoutEffect, useRef } from 'react'
import { CLICK_OUTSIDE_BLOCK_CLASS, useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import clsx from 'clsx'
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
    FloatingPortal,
    UseFloatingReturn,
    useMergeRefs,
    hide,
} from '@floating-ui/react'
import { CSSTransition } from 'react-transition-group'
import { useEventListener } from 'lib/hooks/useEventListener'

export interface PopoverProps {
    ref?: React.MutableRefObject<HTMLDivElement | null> | React.Ref<HTMLDivElement> | null
    visible: boolean
    onClickOutside?: (event: Event) => void
    onClickInside?: MouseEventHandler<HTMLDivElement>
    /** Popover trigger element. If you pass one <Component/> child, it will get the `ref` prop automatically. */
    children?: React.ReactChild
    /** External reference element not passed as a direct child */
    referenceElement?: HTMLElement | null
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
    /** Any other refs that needs to be taken into account for handling outside clicks e.g. other nested popovers.
     * Works also with strings, matching classnames or ids, for antd legacy components that don't support refs
     * **/
    additionalRefs?: (React.MutableRefObject<HTMLDivElement | null> | string)[]
    referenceRef?: UseFloatingReturn['refs']['reference']
    style?: React.CSSProperties
    /** Whether the parent popover should be closed as well on click. Useful for menus. */
    closeParentPopoverOnClickInside?: boolean
    getPopupContainer?: () => HTMLElement
    /** Whether to show an arrow pointing to a reference element */
    showArrow?: boolean
}

/** Context for the popover overlay: parent popover visibility and parent popover level. */
export const PopoverOverlayContext = React.createContext<[boolean, number]>([true, -1])
/** Context for the popover reference element (if rendered as a Popover child and not externally). */
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
        closeParentPopoverOnClickInside = false,
        referenceRef: extraReferenceRef,
        style,
        getPopupContainer,
        showArrow = false,
    },
    contentRef
): JSX.Element {
    const [parentPopoverVisibility, parentPopoverLevel] = useContext(PopoverOverlayContext)
    const currentPopoverLevel = parentPopoverLevel + 1

    if (!parentPopoverVisibility) {
        visible = false // Hide all popovers of a hierarchy in sync
    }

    const arrowRef = useRef<HTMLDivElement>(null)
    const {
        x,
        y,
        reference,
        floating,
        refs: { reference: referenceRef, floating: floatingRef },
        strategy,
        placement: effectivePlacement,
        update,
        middlewareData,
    } = useFloating<HTMLElement>({
        open: visible,
        placement,
        strategy: 'fixed',
        middleware: [
            offset(4),
            ...(fallbackPlacements ? [flip({ fallbackPlacements, fallbackStrategy: 'initialPlacement' })] : []),
            shift(),
            size({
                padding: 4,
                apply({ availableWidth, availableHeight, rects, elements: { floating } }) {
                    floating.style.maxHeight = `${availableHeight}px`
                    floating.style.maxWidth = `${availableWidth}px`
                    floating.style.width = sameWidth ? `${rects.reference.width}px` : 'initial'
                },
            }),
            arrow({ element: arrowRef, padding: 8 }),
            hide(),
            ...(middleware ?? []),
        ],
    })
    const mergedReferenceRef = useMergeRefs([referenceRef, extraReferenceRef || null]) as React.RefCallback<HTMLElement>

    const arrowStaticSide = {
        top: 'bottom',
        right: 'left',
        bottom: 'top',
        left: 'right',
    }[effectivePlacement.split('-')[0]] as string

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
        if (visible && referenceRef?.current && floatingRef?.current) {
            return autoUpdate(referenceRef.current, floatingRef.current, update)
        }
    }, [visible, referenceRef?.current, floatingRef?.current, ...additionalRefs])

    const _onClickInside: MouseEventHandler<HTMLDivElement> = (e): void => {
        if (e.target instanceof HTMLElement && e.target.closest(`.${CLICK_OUTSIDE_BLOCK_CLASS}`)) {
            return
        }
        onClickInside?.(e)
        // If we are not the top level popover, set a flag so that other popovers know that.
        if (parentPopoverLevel > 0 && !closeParentPopoverOnClickInside) {
            nestedPopoverReceivedClick = true
            setTimeout(() => {
                nestedPopoverReceivedClick = false
            }, 1)
        }
    }

    const clonedChildren = children ? React.cloneElement(children as ReactElement, { ref: mergedReferenceRef }) : null

    const isAttached = clonedChildren || referenceElement
    const top = isAttached ? y ?? 0 : undefined
    const left = isAttached ? x ?? 0 : undefined

    return (
        <>
            {clonedChildren && (
                <PopoverReferenceContext.Provider value={[visible, effectivePlacement]}>
                    {clonedChildren}
                </PopoverReferenceContext.Provider>
            )}
            <FloatingPortal root={getPopupContainer?.()}>
                <CSSTransition in={visible} timeout={100} classNames="Popover-" appear mountOnEnter unmountOnExit>
                    <PopoverOverlayContext.Provider value={[visible, currentPopoverLevel]}>
                        <div
                            className={clsx(
                                'Popover',
                                actionable && 'Popover--actionable',
                                maxContentWidth && 'Popover--max-content-width',
                                !isAttached && 'Popover--top-centered',
                                className
                            )}
                            data-placement={effectivePlacement}
                            ref={floating}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                display: middlewareData.hide?.referenceHidden ? 'none' : undefined,
                                position: strategy,
                                top,
                                left,
                                ...style,
                            }}
                            onClick={_onClickInside}
                            aria-level={currentPopoverLevel}
                        >
                            <div className="Popover__box">
                                {showArrow && isAttached && (
                                    // Arrow is outside of .Popover__content to avoid affecting :nth-child for content
                                    <div
                                        ref={arrowRef}
                                        className={clsx(
                                            'Popover__arrow',
                                            `Popover__arrow--${arrowStaticSide}`,
                                            actionable && 'Popover--actionable'
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={arrowStyle}
                                    />
                                )}
                                <div className="Popover__content" ref={contentRef}>
                                    {overlay}
                                </div>
                            </div>
                        </div>
                    </PopoverOverlayContext.Provider>
                </CSSTransition>
            </FloatingPortal>
        </>
    )
})

import './PanelLayout.scss'

import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useRef } from 'react'

import { IconX } from '@posthog/icons'

import { IconMenu } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { supportTicketCounterLogic } from 'products/conversations/frontend/supportTicketCounterLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { Nav as AiFirstNavBar } from './ai-first/Nav'
import { PanelLayoutPanels } from './ai-first/PanelLayoutPanels'
import { panelLayoutLogic } from './panelLayoutLogic'
import { PROJECT_TREE_KEY } from './ProjectTree/ProjectTree'
import { projectTreeLogic } from './ProjectTree/projectTreeLogic'

const panelLayoutStyles = cva({
    base: 'gap-0 w-fit relative h-screen z-[var(--z-layout-panel)]',
    variants: {
        isLayoutNavbarVisibleForMobile: {
            true: 'translate-x-0',
            false: '',
        },
        isLayoutNavbarVisibleForDesktop: {
            true: '',
            false: '',
        },
        isLayoutPanelVisible: {
            true: 'block',
            false: 'hidden',
        },
        isMobileLayout: {
            true: 'absolute top-0 bottom-0 flex',
            false: 'grid',
        },
        isLayoutNavCollapsed: {
            true: '',
            false: '',
        },
    },
    compoundVariants: [
        // Old layout mobile: use hidden/block
        {
            isMobileLayout: true,
            isLayoutNavbarVisibleForMobile: true,
            className: 'block',
        },
        {
            isMobileLayout: true,
            isLayoutNavbarVisibleForMobile: false,
            className: 'hidden',
        },
        // Navbar (collapsed)
        {
            isMobileLayout: false,
            isLayoutNavCollapsed: true,
            className: 'w-[var(--project-navbar-width-collapsed)]',
        },
        // Navbar (default)
        {
            isMobileLayout: false,
            isLayoutNavCollapsed: false,
            className: 'w-[var(--project-navbar-width)]',
        },
    ],
})

export function PanelLayout({ className }: { className?: string }): JSX.Element {
    const {
        isLayoutPanelVisible,
        isLayoutNavbarVisibleForMobile,
        isLayoutNavbarVisibleForDesktop,
        isLayoutNavCollapsed,
        panelWidth,
        activePanelIdentifier,
    } = useValues(panelLayoutLogic)
    // Panels can be surfaced from URL state (DataAndPeople, DataManagement) without flipping
    // isLayoutPanelVisible — so for overlay visibility we key off the identifier directly.
    const panelIsShown = isLayoutPanelVisible || activePanelIdentifier !== ''
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, clearActivePanelIdentifier, showLayoutNavBar } = useActions(panelLayoutLogic)
    useMountedLogic(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    useMountedLogic(supportTicketCounterLogic) // Start polling for unread tickets on app load

    const navContainerRef = useRef<HTMLDivElement>(null)

    // On mobile this is the only navigation control, and its whole response is the nav sliding in.
    // Driving that slide purely off React state means the commit that applies the transform is
    // shared with — and can be starved by — a heavy scene mounting, so the toggle looks dead for
    // seconds after a navigation. Writing the open state to a data attribute here, in the click
    // handler, lets the CSS transition fire immediately regardless of the main thread; the action
    // still runs so React state (icon, aria-expanded, scrims) catches up once the scene settles.
    const toggleMobileNav = (): void => {
        const nextVisible = !isLayoutNavbarVisibleForMobile
        navContainerRef.current?.setAttribute('data-mobile-nav-open', String(nextVisible))
        showLayoutNavBar(nextVisible)
    }

    return (
        <>
            {isMobileLayout && (
                <ButtonPrimitive
                    onClick={toggleMobileNav}
                    iconOnly
                    aria-label={isLayoutNavbarVisibleForMobile ? 'Close navigation' : 'Open navigation'}
                    aria-expanded={isLayoutNavbarVisibleForMobile}
                    className="fixed top-1 left-1 z-760 rounded-lg bg-surface-primary border border-primary shadow-sm"
                >
                    {isLayoutNavbarVisibleForMobile ? <IconX /> : <IconMenu />}
                </ButtonPrimitive>
            )}
            <div
                ref={navContainerRef}
                id="project-panel-layout"
                // Slide state lives in a data attribute (not an inline transform) so the click
                // handler can paint it without waiting for a React commit — see toggleMobileNav.
                data-mobile-nav-open={isMobileLayout ? String(isLayoutNavbarVisibleForMobile) : undefined}
                className={cn(
                    panelLayoutStyles({
                        isLayoutNavbarVisibleForMobile,
                        isLayoutNavbarVisibleForDesktop,
                        isLayoutPanelVisible,
                        isMobileLayout,
                        isLayoutNavCollapsed,
                    }),
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    isMobileLayout
                        ? ({
                              // The slide transform/transition live in PanelLayout.scss, keyed off
                              // data-mobile-nav-open, so the toggle can drive them outside React.
                              '--project-panel-width': `${panelWidth}px`,
                              position: 'fixed' as const,
                              top: 0,
                              left: 0,
                              bottom: 0,
                              width: 'var(--project-navbar-width)',
                              // Container holds the nav only on mobile (panel renders separately
                              // below). Drop its z to the navbar layer so the dim overlay can slot
                              // between nav (this container) and the panel.
                              zIndex: 'var(--z-layout-navbar)',
                          } as React.CSSProperties)
                        : {}
                }
            >
                <AiFirstNavBar />
            </div>

            {/* Mobile-only positioning anchor for panel content. Decoupled from #project-panel-layout
                so the panel gets its own stacking context at --z-layout-panel. The wrapper is
                left:0 width:0 — PanelLayoutPanel's inner nav uses absolute left:var(--panel-layout-mobile-offset)
                which resolves against this wrapper's 0-width left edge → lands at viewport 40px.
                pointer-events:none so the empty wrapper area doesn't intercept clicks on the dim
                or right overlays — panel content re-enables pointer-events via its own cva. */}
            {isMobileLayout && (
                <div
                    className="fixed top-0 left-0 h-screen z-[var(--z-layout-panel)] pointer-events-none"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: 0 }}
                >
                    <div className="relative h-full">
                        <PanelLayoutPanels />
                    </div>
                </div>
            )}

            {/* Panel dim overlay — click closes the panel. On mobile hugs the visible nav strip
                (the 40px the panel doesn't cover); on desktop covers the full viewport. */}
            <div
                onClick={() => {
                    showLayoutPanel(false)
                    clearActivePanelIdentifier()
                }}
                className={cn(
                    // visibility joins the transition so the fade-out still plays, but once hidden the
                    // full-viewport layer stops being rasterized — at opacity-0 alone the compositor
                    // keeps a viewport-sized tile backing alive for this scrim for every app view that mounts the layout
                    'z-(--z-layout-panel-over-nav) md:z-(--z-layout-panel-under) fixed top-0 bottom-0 bg-fill-highlight-200 dark:bg-black/80 transition-[opacity,visibility] duration-200',
                    isMobileLayout
                        ? 'left-0 w-[var(--panel-layout-mobile-offset)]'
                        : 'left-0 right-0 w-screen h-screen',
                    !panelIsShown && 'pointer-events-none opacity-0 invisible'
                )}
                aria-hidden={!panelIsShown}
            />

            {/* Mobile navbar overlay — sits right of the nav (and panel when open) so a tap
                "right of panel" closes everything. */}
            <div
                onClick={() => {
                    showLayoutNavBar(false)
                    showLayoutPanel(false)
                    clearActivePanelIdentifier()
                }}
                className={cn(
                    'z-(--z-layout-navbar-under) md:z-(--z-layout-navbar) fixed top-0 bottom-0 right-0 bg-fill-highlight-200 dark:bg-black/80 transition-[opacity,visibility] duration-200',
                    isMobileLayout ? 'left-(--project-navbar-width)' : 'left-0 w-screen h-screen',
                    !(isMobileLayout && isLayoutNavbarVisibleForMobile) && 'pointer-events-none opacity-0 invisible'
                )}
                // visibility joins the transition here too — see the panel scrim comment above
                aria-hidden={!(isMobileLayout && isLayoutNavbarVisibleForMobile)}
            />
        </>
    )
}

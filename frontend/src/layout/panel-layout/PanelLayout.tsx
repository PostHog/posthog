import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { useEffect, useRef } from 'react'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { panelLayoutLogic } from './panelLayoutLogic'
import { PanelLayoutNavBar } from './PanelLayoutNavBar'
import { ProjectTree } from './ProjectTree/ProjectTree'
import { projectTreeLogic } from './ProjectTree/projectTreeLogic'

const panelLayoutStyles = cva({
    base: 'gap-0 w-fit relative h-screen z-[var(--z-project-panel-layout)]',
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
            true: '',
            false: '',
        },
        isLayoutPanelPinned: {
            true: '',
            false: '',
        },
        isMobileLayout: {
            true: 'flex absolute top-0 bottom-0 left-0',
            false: 'grid',
        },
        isLayoutNavCollapsed: {
            true: '',
            false: '',
        },
    },
    compoundVariants: [
        {
            isMobileLayout: true,
            isLayoutNavbarVisibleForMobile: true,
            className: 'translate-x-0',
        },
        {
            isMobileLayout: true,
            isLayoutNavbarVisibleForMobile: false,
            className: 'translate-x-[calc(var(--project-navbar-width)*-1)]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: false,
            className: 'w-[calc(var(--project-navbar-width)+var(--project-panel-width))]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: true,
            className: 'w-[calc(var(--project-navbar-width-collapsed)+var(--project-panel-width))]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: false,
            isLayoutNavCollapsed: true,
            className: 'w-[var(--project-navbar-width-collapsed)]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: false,
            isLayoutNavCollapsed: false,
            className: 'w-[var(--project-navbar-width)]',
        },
    ],
})

export function PanelLayout({ mainRef }: { mainRef: React.RefObject<HTMLElement> }): JSX.Element {
    const {
        isLayoutPanelPinned,
        isLayoutPanelVisible,
        isLayoutNavbarVisibleForMobile,
        isLayoutNavbarVisibleForDesktop,
        activePanelIdentifier,
        isLayoutNavCollapsed,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, showLayoutNavBar, clearActivePanelIdentifier, setMainContentRef } =
        useActions(panelLayoutLogic)
    const showMobileNavbarOverlay = isLayoutNavbarVisibleForMobile
    const showDesktopNavbarOverlay = isLayoutNavbarVisibleForDesktop && !isLayoutPanelPinned && isLayoutPanelVisible
    useMountedLogic(projectTreeLogic)

    const containerRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
        }
    }, [mainRef, setMainContentRef])

    return (
        <div className="relative" ref={containerRef}>
            <div
                id="project-panel-layout"
                className={cn(
                    panelLayoutStyles({
                        isLayoutNavbarVisibleForMobile,
                        isLayoutNavbarVisibleForDesktop,
                        isLayoutPanelPinned,
                        isLayoutPanelVisible,
                        isMobileLayout,
                        isLayoutNavCollapsed,
                    })
                )}
            >
                <PanelLayoutNavBar>
                    {activePanelIdentifier === 'Project' && <ProjectTree />}
                    {/* {activePanelIdentifier === 'persons' && <PersonsTree />} */}
                </PanelLayoutNavBar>
            </div>

            {isMobileLayout && showMobileNavbarOverlay && (
                <div
                    onClick={() => {
                        // Pinned or not, hide the navbar and panel
                        showLayoutNavBar(false)
                        showLayoutPanel(false)
                        clearActivePanelIdentifier()
                    }}
                    className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"
                />
            )}
            {!isMobileLayout && showDesktopNavbarOverlay && (
                <div
                    onClick={() => {
                        if (!isLayoutPanelPinned) {
                            showLayoutPanel(false)
                            clearActivePanelIdentifier()
                        }
                    }}
                    className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"
                />
            )}
        </div>
    )
}

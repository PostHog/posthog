import { cva } from 'class-variance-authority'
import { useActions, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { useEffect } from 'react'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { panelLayoutLogic } from './panelLayoutLogic'
import { PanelLayoutNavBar } from './PanelLayoutNavBar'
// import { PersonsTree } from './PersonsTree/PersonsTree'
import { ProjectTree } from './ProjectTree/ProjectTree'

const panelLayoutStyles = cva('gap-0 w-fit relative h-screen z-[var(--z-project-panel-layout)]', {
    variants: {
        isLayoutNavbarVisibleForMobile: {
            true: 'translate-x-0',
            false: '',
        },
        isLayoutNavbarVisibleForDesktop: {
            true: 'w-[var(--project-navbar-width)]',
            false: '',
        },
        isLayoutPanelVisible: {
            true: '',
            false: 'w-[var(--project-navbar-width)]',
        },
        isLayoutPanelPinned: {
            true: '',
            false: '',
        },
        isMobileLayout: {
            true: 'flex absolute top-0 bottom-0 left-0',
            false: 'grid',
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
            className: 'w-[calc(var(--project-navbar-width)+var(--project-panel-width))]',
        },
    ],
    defaultVariants: {
        isLayoutPanelPinned: false,
        isLayoutPanelVisible: false,
    },
})

export function PanelLayout({ mainRef }: { mainRef: React.RefObject<HTMLElement> }): JSX.Element {
    const {
        isLayoutPanelPinned,
        isLayoutPanelVisible,
        isLayoutNavbarVisibleForMobile,
        isLayoutNavbarVisibleForDesktop,
        activePanelIdentifier,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, showLayoutNavBar, clearActivePanelIdentifier, setMainContentRef } =
        useActions(panelLayoutLogic)
    const showMobileNavbarOverlay = isLayoutNavbarVisibleForMobile
    const showDesktopNavbarOverlay = isLayoutNavbarVisibleForDesktop && !isLayoutPanelPinned && isLayoutPanelVisible

    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
        }
    }, [mainRef, setMainContentRef])

    return (
        <div className="relative">
            <div
                id="project-panel-layout"
                className={cn(
                    panelLayoutStyles({
                        isLayoutNavbarVisibleForMobile,
                        isLayoutNavbarVisibleForDesktop,
                        isLayoutPanelPinned,
                        isLayoutPanelVisible,
                        isMobileLayout,
                    })
                )}
            >
                <PanelLayoutNavBar>
                    {activePanelIdentifier === 'project' && <ProjectTree />}
                    {/* {activePanelIdentifier === 'persons' && <PersonsTree />} */}
                </PanelLayoutNavBar>
            </div>

            {isMobileLayout && showMobileNavbarOverlay && (
                <div
                    onClick={() => {
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
                        showLayoutPanel(false)
                        clearActivePanelIdentifier()
                    }}
                    className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"
                />
            )}
        </div>
    )
}

import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { useEffect } from 'react'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { panelLayoutLogic } from './panelLayoutLogic'
import { PanelLayoutNavBar } from './PanelLayoutNavBar'
import { PROJECT_TREE_KEY, ProjectTree } from './ProjectTree/ProjectTree'
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
        isLayoutPanelPinned: {
            true: '',
            false: '',
        },
        isMobileLayout: {
            true: 'absolute top-0 bottom-0 flex',
            false: 'grid',
        },
        isLayoutNavCollapsed: {
            true: '',
            false: '',
        },
        projectTreeMode: {
            tree: '',
            table: '',
        },
    },
    compoundVariants: [
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
        // Tree mode
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: false,
            projectTreeMode: 'tree',
            className: 'w-[calc(var(--project-navbar-width)+var(--project-panel-width))]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: true,
            projectTreeMode: 'tree',
            className: 'w-[calc(var(--project-navbar-width-collapsed)+var(--project-panel-width))]',
        },
        // Table mode
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: false,
            projectTreeMode: 'table',
            // The panel in table mode is positioned absolutely, so we need to set the width to the navbar width
            className: 'w-[calc(var(--project-navbar-width)+var(--project-panel-width))]',
        },
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: true,
            isLayoutNavCollapsed: true,
            projectTreeMode: 'table',
            // The panel in table mode is positioned absolutely, so we need to set the width to the navbar width (collapsed)
            className: 'w-[calc(var(--project-navbar-width-collapsed)+var(--project-panel-width))]',
        },
        // Navbar (collapsed)
        {
            isMobileLayout: false,
            isLayoutPanelVisible: true,
            isLayoutPanelPinned: false,
            isLayoutNavCollapsed: true,
            className: 'w-[var(--project-navbar-width-collapsed)]',
        },
        // Navbar (default)
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
        panelWidth,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, clearActivePanelIdentifier, setMainContentRef } = useActions(panelLayoutLogic)
    const { projectTreeMode } = useValues(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { setProjectTreeMode } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    useMountedLogic(projectTreeLogic({ key: PROJECT_TREE_KEY }))

    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
        }
    }, [mainRef, setMainContentRef])

    return (
        <>
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
                        projectTreeMode: projectTreeMode,
                    })
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--project-panel-width': `${panelWidth}px` } as React.CSSProperties}
            >
                <PanelLayoutNavBar>
                    {activePanelIdentifier === 'Project' && (
                        <ProjectTree
                            root="project://"
                            sortMethod="folder"
                            logicKey={PROJECT_TREE_KEY}
                            searchPlaceholder="Search by user, type, or name"
                        />
                    )}
                    {activePanelIdentifier === 'Recent' && (
                        <ProjectTree
                            root="project://"
                            sortMethod="recent"
                            logicKey={PROJECT_TREE_KEY}
                            searchPlaceholder="Search by user, type, or name"
                        />
                    )}
                    {activePanelIdentifier === 'Products' && (
                        <ProjectTree root="products://" searchPlaceholder="Search products" />
                    )}
                    {activePanelIdentifier === 'Shortcuts' && (
                        <ProjectTree root="shortcuts://" searchPlaceholder="Search your shortcuts" />
                    )}
                    {activePanelIdentifier === 'Data' && (
                        <ProjectTree root="data-management://" searchPlaceholder="Search data" />
                    )}
                    {activePanelIdentifier === 'People' && (
                        <ProjectTree root="persons://" searchPlaceholder="Search persons" />
                    )}
                </PanelLayoutNavBar>
            </div>

            {isLayoutPanelVisible && !isLayoutPanelPinned && (
                <div
                    onClick={() => {
                        showLayoutPanel(false)
                        clearActivePanelIdentifier()
                    }}
                    className="z-[var(--z-layout-panel-under)] fixed inset-0 w-screen h-screen"
                />
            )}

            {projectTreeMode === 'table' && (
                <div
                    onClick={() => {
                        // Return to tree mode when clicking outside the table view
                        setProjectTreeMode('tree')
                    }}
                    className="z-[var(--z-layout-navbar-under)] fixed inset-0 w-screen h-screen"
                />
            )}
        </>
    )
}

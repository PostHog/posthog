import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { AiFirstNavBar } from './AiFirstNavBar'
import { PanelLayoutNavBar } from './PanelLayoutNavBar'
import { PROJECT_TREE_KEY, ProjectTree } from './ProjectTree/ProjectTree'
import { projectTreeLogic } from './ProjectTree/projectTreeLogic'
import { panelLayoutLogic } from './panelLayoutLogic'

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
        activePanelIdentifier,
        isLayoutNavCollapsed,
        panelWidth,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, clearActivePanelIdentifier, showLayoutNavBar } = useActions(panelLayoutLogic)
    useMountedLogic(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const isAIFirst = useFeatureFlag('AI_FIRST')

    return (
        <>
            <div
                id="project-panel-layout"
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
                              // Use CSS transform for slide animation
                              '--project-panel-width': `${panelWidth}px`,
                              position: 'fixed' as const,
                              top: 0,
                              left: 0,
                              bottom: 0,
                              width: 'var(--project-navbar-width)',
                              transform: isLayoutNavbarVisibleForMobile ? 'translateX(0)' : 'translateX(-100%)',
                              transition: 'transform 0.2s ease-out',
                              zIndex: 'var(--z-layout-panel)',
                          } as React.CSSProperties)
                        : {}
                }
            >
                {isAIFirst ? (
                    <AiFirstNavBar />
                ) : (
                    <PanelLayoutNavBar>
                        {activePanelIdentifier === 'Project' && (
                            <ProjectTree
                                root="project://"
                                logicKey={PROJECT_TREE_KEY}
                                searchPlaceholder="Search by user, type, or name"
                                showRecents
                            />
                        )}
                        {activePanelIdentifier === 'Products' && (
                            <ProjectTree root="products://" searchPlaceholder="Search apps" />
                        )}
                        {activePanelIdentifier === 'Shortcuts' && (
                            <ProjectTree root="shortcuts://" searchPlaceholder="Search your shortcuts" />
                        )}
                        {activePanelIdentifier === 'DataManagement' && (
                            <ProjectTree root="data://" searchPlaceholder="Search data tools" />
                        )}
                        {activePanelIdentifier === 'People' && (
                            <ProjectTree root="persons://" searchPlaceholder="Search people tools" />
                        )}
                    </PanelLayoutNavBar>
                )}
            </div>

            {/* Panel overlay - always rendered for exit animation */}
            <div
                onClick={() => {
                    showLayoutPanel(false)
                    clearActivePanelIdentifier()
                }}
                className={cn(
                    'z-[var(--z-layout-panel-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-200 dark:bg-black/80 overlay-fade',
                    !isLayoutPanelVisible && 'pointer-events-none opacity-0'
                )}
                aria-hidden={!isLayoutPanelVisible}
            />

            {/* Mobile overlay for new app-layout - outside transformed container so it fades instead of slides */}
            <div
                onClick={() => {
                    showLayoutNavBar(false)
                    clearActivePanelIdentifier()
                }}
                className={cn(
                    'z-[var(--z-layout-navbar-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-200 dark:bg-black/80 overlay-fade',
                    !(isMobileLayout && isLayoutNavbarVisibleForMobile) && 'pointer-events-none opacity-0'
                )}
                aria-hidden={!(isMobileLayout && isLayoutNavbarVisibleForMobile)}
            />
        </>
    )
}

import { cva } from 'class-variance-authority'
import { useActions, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'

import { ProjectTree } from '~/layout/navigation-3000/components/ProjectTree/ProjectTree'
import { ProjectTreeNavbar } from '~/layout/navigation-3000/components/ProjectTree/ProjectTreeNavbar'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { projectPanelLayoutLogic } from './projectPanelLayoutLogic'

const panelLayoutStyles = cva('gap-0 w-fit relative h-screen z-[var(--z-project-panel-layout)]', {
    variants: {
        isNavbarVisibleMobile: {
            true: 'translate-x-0',
            false: '',
        },
        isNavbarVisibleDesktop: {
            true: 'w-[var(--project-navbar-width)]',
            false: '',
        },
        isPanelVisible: {
            true: '',
            false: 'w-[var(--project-navbar-width)]',
        },
        isPanelPinned: {
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
            isNavbarVisibleMobile: true,
            className: 'translate-x-0',
        },
        {
            isMobileLayout: true,
            isNavbarVisibleMobile: false,
            className: 'translate-x-[calc(var(--project-navbar-width)*-1)]',
        },
        {
            isMobileLayout: false,
            isPanelVisible: true,
            isPanelPinned: true,
            className: 'w-[calc(var(--project-navbar-width)+var(--project-panel-width))]',
        },
    ],
    defaultVariants: {
        isPanelPinned: false,
        isPanelVisible: false,
    },
})

export function ProjectPanelLayout({ mainRef }: { mainRef: React.RefObject<HTMLElement> }): JSX.Element {
    const { isPanelPinned, isPanelVisible, isNavbarVisibleMobile, isNavbarVisibleDesktop } =
        useValues(projectPanelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { togglePanelVisible, showNavBar } = useActions(projectPanelLayoutLogic)

    const showMobileNavbarOverlay = isNavbarVisibleMobile
    const showDesktopNavbarOverlay = isNavbarVisibleDesktop && !isPanelPinned && isPanelVisible

    return (
        <div className="relative">
            <div
                id="project-panel-layout"
                className={cn(
                    panelLayoutStyles({
                        isNavbarVisibleMobile,
                        isNavbarVisibleDesktop,
                        isPanelPinned,
                        isPanelVisible,
                        isMobileLayout,
                    })
                )}
            >
                <ProjectTreeNavbar>
                    <ProjectTree contentRef={mainRef} />
                </ProjectTreeNavbar>
            </div>

            {isMobileLayout && showMobileNavbarOverlay && (
                <div
                    onClick={() => {
                        showNavBar(false)
                        togglePanelVisible(false)
                    }}
                    className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"
                />
            )}
            {!isMobileLayout && showDesktopNavbarOverlay && (
                <div
                    onClick={() => {
                        togglePanelVisible(false)
                    }}
                    className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"
                />
            )}
        </div>
    )
}

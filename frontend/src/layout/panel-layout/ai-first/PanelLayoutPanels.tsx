import { useActions, useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { NotificationsPanel } from 'lib/components/NotificationsMenu/NotificationsPanel'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { PROJECT_TREE_KEY, ProjectTree } from '../ProjectTree/ProjectTree'

const NavTabChat = lazy(() => import('./tabs/NavTabChat').then((m) => ({ default: m.NavTabChat })))

// Renders the currently-active panel (Project tree, Notifications, Chat, etc.). Extracted so the
// same active-panel JSX can be mounted at different positions in the DOM/stacking tree depending
// on layout mode — inside the nav container on desktop, as a fixed sibling on mobile.
export function PanelLayoutPanels(): JSX.Element | null {
    const { activePanelIdentifier } = useValues(panelLayoutLogic)
    const { clearActivePanelIdentifier, showLayoutPanel } = useActions(panelLayoutLogic)

    if (activePanelIdentifier === 'DataAndPeople') {
        return <ProjectTree root="data-and-people://" searchPlaceholder="Search data" />
    }
    if (activePanelIdentifier === 'Project') {
        return (
            <ProjectTree root="project://" logicKey={PROJECT_TREE_KEY} searchPlaceholder="Search files" showRecents />
        )
    }
    if (activePanelIdentifier === 'Products') {
        return <ProjectTree root="products://" searchPlaceholder="Search apps" />
    }
    if (activePanelIdentifier === 'Shortcuts') {
        return <ProjectTree root="shortcuts://" searchPlaceholder="Search starred items" />
    }
    if (activePanelIdentifier === 'Notifications') {
        return <NotificationsPanel />
    }
    if (activePanelIdentifier === 'Chat') {
        return (
            <div className="pointer-events-auto flex flex-col h-full min-h-screen max-h-screen bg-surface-tertiary border-r overflow-hidden w-[var(--project-panel-width)]">
                <Suspense
                    fallback={
                        <div className="flex flex-col gap-px px-1 pt-2">
                            {Array.from({ length: 15 }).map((_, index) => (
                                <WrappingLoadingSkeleton fullWidth key={index}>
                                    <ButtonPrimitive aria-hidden inert menuItem />
                                </WrappingLoadingSkeleton>
                            ))}
                        </div>
                    }
                >
                    <NavTabChat
                        inPanel
                        onItemClick={() => {
                            clearActivePanelIdentifier()
                            showLayoutPanel(false)
                        }}
                    />
                </Suspense>
            </div>
        )
    }
    return null
}

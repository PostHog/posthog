import { useActions, useValues } from 'kea'
import { lazy, Suspense, useCallback } from 'react'

import { NotificationsPanel } from 'lib/components/NotificationsMenu/NotificationsPanel'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'

import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { PROJECT_TREE_KEY, ProjectTree } from '../ProjectTree/ProjectTree'

const NavTabChat = lazy(() => import('./tabs/NavTabChat').then((m) => ({ default: m.NavTabChat })))

// Panels that stay mounted (hidden) once opened, so switching panels doesn't tear down and rebuild
// whole trees on every toggle — that churn showed up as the app's dominant detached-DOM source, and
// unmounting also loses scroll/search/expansion state. Notifications is deliberately excluded: its
// logic drives unread/read semantics that should only run while the panel is actually open.
const KEEP_MOUNTED_PANELS: PanelLayoutNavIdentifier[] = ['DataAndPeople', 'Project', 'Products', 'Shortcuts', 'Chat']

// Renders the currently-active panel (Project tree, Notifications, Chat, etc.). Extracted so the
// same active-panel JSX can be mounted at different positions in the DOM/stacking tree depending
// on layout mode — inside the nav container on desktop, as a fixed sibling on mobile.
export function PanelLayoutPanels(): JSX.Element | null {
    const { activePanelIdentifier, visitedPanels } = useValues(panelLayoutLogic)
    const { clearActivePanelIdentifier, showLayoutPanel } = useActions(panelLayoutLogic)

    // Stable reference: the chat panel stays mounted now, so a fresh closure here would re-render
    // NavTabChat's memoized internals on every re-render of this component.
    const onChatItemClick = useCallback(() => {
        clearActivePanelIdentifier()
        showLayoutPanel(false)
    }, [clearActivePanelIdentifier, showLayoutPanel])

    const panelContent: Partial<Record<PanelLayoutNavIdentifier, JSX.Element>> = {
        DataAndPeople: <ProjectTree root="data-and-people://" searchPlaceholder="Search data" />,
        Project: (
            <ProjectTree root="project://" logicKey={PROJECT_TREE_KEY} searchPlaceholder="Search files" showRecents />
        ),
        Products: <ProjectTree root="products://" searchPlaceholder="Search tools" />,
        Shortcuts: <ProjectTree root="shortcuts://" searchPlaceholder="Search starred items" />,
        Chat: (
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
                    <NavTabChat inPanel onItemClick={onChatItemClick} />
                </Suspense>
            </div>
        ),
    }

    return (
        <>
            {KEEP_MOUNTED_PANELS.filter(
                (identifier) => identifier === activePanelIdentifier || visitedPanels.includes(identifier)
            ).map((identifier) => (
                // `contents` keeps the wrapper out of layout when active, so each panel's own
                // chrome positions exactly as it did when returned bare from this component.
                <div key={identifier} className={identifier === activePanelIdentifier ? 'contents' : 'hidden'}>
                    {panelContent[identifier]}
                </div>
            ))}
            {activePanelIdentifier === 'Notifications' && <NotificationsPanel />}
        </>
    )
}

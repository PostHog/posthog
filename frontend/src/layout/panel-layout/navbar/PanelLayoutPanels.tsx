import { useValues } from 'kea'

import { NotificationsPanel } from 'lib/components/NotificationsMenu/NotificationsPanel'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { ProjectTree } from '../ProjectTree/ProjectTree'
import { PROJECT_TREE_KEY } from '../ProjectTree/projectTreeLogic'

// Renders the currently-active panel (Project tree or Notifications). Extracted so the
// same active-panel JSX can be mounted at different positions in the DOM/stacking tree depending
// on layout mode — inside the nav container on desktop, as a fixed sibling on mobile.
export function PanelLayoutPanels(): JSX.Element | null {
    const { activePanelIdentifier, visitedPanels } = useValues(panelLayoutLogic)
    const isProjectActive = activePanelIdentifier === 'Project'

    return (
        <>
            {/* The project tree stays mounted (hidden) once opened, so closing and reopening it keeps its
                scroll and expansion state instead of rebuilding the whole tree. */}
            {(isProjectActive || visitedPanels.includes('Project')) && (
                <div className={isProjectActive ? 'contents' : 'hidden'}>
                    <ProjectTree
                        panelName="project"
                        root="project://"
                        logicKey={PROJECT_TREE_KEY}
                        searchPlaceholder="Search files"
                        showRecents
                        isActiveInPanel={isProjectActive}
                    />
                </div>
            )}
            {/* Notifications only mounts while open, because its logic marks notifications as read. */}
            {activePanelIdentifier === 'Notifications' && <NotificationsPanel />}
        </>
    )
}

import { ComponentType, lazy } from 'react'

import { IconChat, IconLock, IconPulse } from '@posthog/icons'

import { ScenePanelTabConfig } from 'scenes/sceneTypes'

interface ScenePanelProps {
    isScenePanel?: boolean
}

// Lazy load heavy sidepanel components to avoid circular dependency issues
// These components have deep dependency chains that can cause initialization order problems
const SidePanelDiscussion = lazy(() =>
    import('~/layout/navigation-3000/sidepanel/panels/discussion/SidePanelDiscussion').then((m) => ({
        default: m.SidePanelDiscussion as ComponentType<ScenePanelProps>,
    }))
)
const SidePanelActivity = lazy(() =>
    import('~/layout/navigation-3000/sidepanel/panels/activity/SidePanelActivity').then((m) => ({
        default: m.SidePanelActivity as ComponentType<ScenePanelProps>,
    }))
)
const SidePanelAccessControl = lazy(() =>
    import('~/layout/navigation-3000/sidepanel/panels/access_control/SidePanelAccessControl').then((m) => ({
        default: m.SidePanelAccessControl as ComponentType<ScenePanelProps>,
    }))
)

// Wrapper components that pass isScenePanel prop to the sidepanel components
const ScenePanelDiscussion = (): JSX.Element => <SidePanelDiscussion isScenePanel />
const ScenePanelActivity = (): JSX.Element => <SidePanelActivity isScenePanel />
const ScenePanelAccessControl = (): JSX.Element => <SidePanelAccessControl isScenePanel />

/**
 * Global scene panel tabs that can be composed into any scene's scenePanelTabs config.
 * These are common panels like Discussion and Activity that many scenes will want.
 */
export const GLOBAL_SCENE_PANEL_TABS = {
    discussion: {
        id: 'discussion',
        label: 'Discussions',
        Icon: IconChat,
        Content: ScenePanelDiscussion,
    },
    activity: {
        id: 'activity',
        label: 'Team activity',
        Icon: IconPulse,
        Content: ScenePanelActivity,
    },
    accessControl: {
        id: 'access-control',
        label: 'Access control',
        Icon: IconLock,
        Content: ScenePanelAccessControl,
    },
} as const satisfies Record<string, ScenePanelTabConfig>

/**
 * Default tabs to use when a scene wants the standard panel experience.
 * Includes Discussion and Activity tabs.
 */
export const DEFAULT_SCENE_PANEL_TABS: ScenePanelTabConfig[] = [
    GLOBAL_SCENE_PANEL_TABS.discussion,
    GLOBAL_SCENE_PANEL_TABS.activity,
    GLOBAL_SCENE_PANEL_TABS.accessControl,
]

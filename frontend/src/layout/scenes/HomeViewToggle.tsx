import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { sceneLogic } from '~/scenes/sceneLogic'
import { emptySceneParams } from '~/scenes/scenes'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { urls } from '~/scenes/urls'

export type HomeView = 'launchpad' | 'search' | 'apps' | 'files'

// Launchpad is the project default, represented by a null homepage
const homeViewTabs: Record<Exclude<HomeView, 'launchpad'>, SceneTab> = {
    search: {
        id: 'homepage-new-tab',
        pathname: urls.newTab(),
        search: '',
        hash: '',
        title: 'Search',
        iconType: 'search',
        sceneId: Scene.NewTab,
        sceneKey: 'newTab',
        sceneParams: emptySceneParams,
    },
    apps: {
        id: 'homepage-apps',
        pathname: urls.apps(),
        search: '',
        hash: '',
        title: 'Apps',
        iconType: 'tools',
        sceneId: Scene.Apps,
        sceneKey: 'apps',
        sceneParams: emptySceneParams,
    },
    files: {
        id: 'homepage-files',
        pathname: urls.files(),
        search: '',
        hash: '',
        title: 'Files',
        iconType: 'folder',
        sceneId: Scene.Files,
        sceneKey: 'files',
        sceneParams: emptySceneParams,
    },
}

/** Gear button in the top-left of the home views that expands into the homepage picker. */
export function HomeViewToggle({ current }: { current: HomeView }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const { setHomepage } = useActions(sceneLogic)

    return (
        <div className="absolute top-2 left-2 z-20 flex items-center gap-1">
            <LemonButton
                size="small"
                icon={<IconGear />}
                active={expanded}
                tooltip="Configure home"
                onClick={() => setExpanded(!expanded)}
                data-attr="home-view-toggle-gear"
                aria-label="Configure home"
            />
            {expanded && (
                <LemonSegmentedButton
                    size="small"
                    value={current}
                    onChange={(view: HomeView) => {
                        if (view === current) {
                            return
                        }
                        posthog.capture('homepage configure set homepage', {
                            'homepage choice': view,
                            source: 'home view toggle',
                        })
                        setHomepage(view === 'launchpad' ? null : homeViewTabs[view])
                        router.actions.push(view === 'launchpad' ? urls.projectHomepage() : homeViewTabs[view].pathname)
                    }}
                    options={[
                        {
                            value: 'launchpad' as const,
                            label: 'Launchpad',
                            'data-attr': 'home-view-toggle-launchpad',
                            tooltip: 'An AI-powered home with quick actions and recent items',
                        },
                        {
                            value: 'search' as const,
                            label: 'Search',
                            'data-attr': 'home-view-toggle-search',
                            tooltip: 'A search page to quickly find anything in your project',
                        },
                        {
                            value: 'apps' as const,
                            label: 'Apps',
                            'data-attr': 'home-view-toggle-apps',
                            tooltip: 'A grid of all the apps and data tools in PostHog',
                        },
                        {
                            value: 'files' as const,
                            label: 'Files',
                            'data-attr': 'home-view-toggle-files',
                            tooltip: 'All the files in your project',
                        },
                    ]}
                />
            )}
        </div>
    )
}

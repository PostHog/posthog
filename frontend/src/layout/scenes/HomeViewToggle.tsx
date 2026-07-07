import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { sceneLogic } from '~/scenes/sceneLogic'
import { emptySceneParams } from '~/scenes/scenes'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { urls } from '~/scenes/urls'

export type HomeView = 'launchpad' | 'search' | 'apps' | 'files'

function TooltipWithKeybind({ text, keybind }: { text: string; keybind: string[] }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span>{text}</span>
            <RenderKeybind keybind={[keybind]} />
        </div>
    )
}

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

/** Homepage picker in the top-left of the home views. Renders in-flow with `inline`, overlaid otherwise. */
export function HomeViewToggle({ current, inline }: { current: HomeView; inline?: boolean }): JSX.Element | null {
    const { setHomepage } = useActions(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { mobileLayout } = useValues(navigation3000Logic)

    if (!featureFlags[FEATURE_FLAGS.HOME_VIEW_TOGGLE]) {
        return null
    }

    return (
        <div
            className={cn(
                'flex items-center gap-1',
                !inline && 'absolute top-2 z-20',
                // The mobile nav hamburger sits fixed at the top left, so step out of its way
                !inline && (mobileLayout ? 'left-12' : 'left-2'),
                inline && mobileLayout && 'ml-10'
            )}
        >
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
                        tooltip: (
                            <TooltipWithKeybind
                                text="An AI-powered home with quick actions and recent items"
                                keybind={keyBinds.homeLaunchpad}
                            />
                        ),
                    },
                    {
                        value: 'search' as const,
                        label: 'Search',
                        'data-attr': 'home-view-toggle-search',
                        tooltip: (
                            <TooltipWithKeybind
                                text="A search page to quickly find anything in your project"
                                keybind={keyBinds.search}
                            />
                        ),
                    },
                    {
                        value: 'apps' as const,
                        label: 'Apps',
                        'data-attr': 'home-view-toggle-apps',
                        tooltip: (
                            <TooltipWithKeybind
                                text="A grid of all the apps and data tools in PostHog"
                                keybind={keyBinds.homeApps}
                            />
                        ),
                    },
                    {
                        value: 'files' as const,
                        label: 'Files',
                        'data-attr': 'home-view-toggle-files',
                        tooltip: (
                            <TooltipWithKeybind text="All the files in your project" keybind={keyBinds.homeFiles} />
                        ),
                    },
                ]}
            />
        </div>
    )
}

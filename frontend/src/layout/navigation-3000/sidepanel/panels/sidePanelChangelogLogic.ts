import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelChangelogLogicType } from './sidePanelChangelogLogicType'

const CHANGELOG_BASE_URL = 'https://posthog.com/changelog'

export const sidePanelChangelogLogic = kea<sidePanelChangelogLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelChangelogLogic']),
    connect(() => ({
        actions: [sidePanelStateLogic, ['closeSidePanel']],
        values: [sceneLogic, ['sceneConfig']],
    })),

    actions({
        setIframeReady: (ready: boolean) => ({ ready }),
    }),

    reducers(() => ({
        iframeReady: [
            false as boolean,
            {
                setIframeReady: (_, { ready }) => ready,
            },
        ],
    })),

    selectors({
        changelogUrl: [
            (s) => [s.sceneConfig],
            (sceneConfig: SceneConfig) => {
                const params = new URLSearchParams()
                if (sceneConfig?.changelogTeamSlug) {
                    params.set('team', sceneConfig.changelogTeamSlug)
                }
                if (sceneConfig?.changelogCategory) {
                    params.set('category', sceneConfig.changelogCategory)
                }
                const queryString = params.toString()
                return queryString ? `${CHANGELOG_BASE_URL}?${queryString}` : CHANGELOG_BASE_URL
            },
        ],
    }),
])

import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { SceneTabKey } from '../../types'
import type { scenesTabsLogicType } from './scenesTabsLogicType'

export type SceneTabConfig = {
    key: SceneTabKey
    label: string
    href: string
}

export const SCENE_TABS: SceneTabConfig[] = [
    {
        key: 'tickets',
        label: 'Tickets',
        href: urls.supportTickets(),
    },
    {
        key: 'broadcasts',
        label: 'Broadcasts',
        href: urls.supportBroadcasts(),
    },
    {
        key: 'settings',
        label: 'Settings',
        href: urls.supportSettings(),
    },
]

export const scenesTabsLogic = kea<scenesTabsLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'ScenesTabs', 'scenesTabsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setTab: (tab: SceneTabKey) => ({ tab }),
        setActiveTab: (tab: SceneTabKey) => ({ tab }),
    }),
    reducers({
        activeTab: [
            'tickets' as SceneTabKey,
            {
                setActiveTab: (_state: SceneTabKey, { tab }: { tab: SceneTabKey }) => tab,
            },
        ],
    }),
    selectors({
        tabs: [
            (s) => [s.featureFlags],
            (featureFlags): SceneTabConfig[] =>
                SCENE_TABS.filter(
                    (tab) => tab.key !== 'broadcasts' || !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_BROADCASTS]
                ),
        ],
    }),
    listeners({
        setTab: ({ tab }: { tab: SceneTabKey }) => {
            const target = SCENE_TABS.find((sceneTab) => sceneTab.key === tab)?.href
            if (target) {
                router.actions.push(target)
            }
        },
    }),
    urlToAction(({ actions }) => {
        return {
            '/support/tickets': () => actions.setActiveTab('tickets'),
            '/support/tickets/:ticketId': () => actions.setActiveTab('tickets'),
            '/support/broadcasts': () => actions.setActiveTab('broadcasts'),
            '/support/settings': () => actions.setActiveTab('settings'),
        }
    }),
])

import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import type { scenesTabsLogicType } from './scenesTabsLogicType'

export type SceneTabKey = 'dashboard' | 'tickets' | 'content' | 'guidance' | 'playground' | 'settings'

export type SceneTabConfig = {
    key: SceneTabKey
    label: string
    href: string
}

export const SCENE_TABS: SceneTabConfig[] = [
    {
        key: 'dashboard',
        label: 'Overview',
        href: urls.conversationsDashboard(),
    },
    {
        key: 'tickets',
        label: 'Tickets',
        href: urls.conversationsTickets(),
    },
    {
        key: 'content',
        label: 'Knowledge base',
        href: urls.conversationsContent(),
    },
    {
        key: 'guidance',
        label: 'Guidance',
        href: urls.conversationsGuidance(),
    },
    {
        key: 'playground',
        label: 'Playground',
        href: urls.conversationsPlayground(),
    },
    {
        key: 'settings',
        label: 'Settings',
        href: urls.conversationsSettings(),
    },
]

export const scenesTabsLogic = kea<scenesTabsLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'ScenesTabs', 'scenesTabsLogic']),
    actions({
        setTab: (tab: SceneTabKey) => ({ tab }),
        setActiveTab: (tab: SceneTabKey) => ({ tab }),
    }),
    reducers({
        activeTab: [
            'dashboard' as SceneTabKey,
            {
                setActiveTab: (_state: SceneTabKey, { tab }: { tab: SceneTabKey }) => tab,
            },
        ],
    }),
    selectors({
        tabs: [() => [], (): SceneTabConfig[] => SCENE_TABS],
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
            '/conversations': () => actions.setActiveTab('dashboard'),
            '/conversations/tickets': () => actions.setActiveTab('tickets'),
            '/conversations/tickets/:ticketId': () => actions.setActiveTab('tickets'),
            '/conversations/content': () => actions.setActiveTab('content'),
            '/conversations/guidance': () => actions.setActiveTab('guidance'),
            '/conversations/playground': () => actions.setActiveTab('playground'),
            '/conversations/settings': () => actions.setActiveTab('settings'),
        }
    }),
])

import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { messagingTabsLogicType } from './messagingTabsLogicType'

export type MessagingTab = 'broadcasts' | 'providers'

export const messagingTabsLogic = kea<messagingTabsLogicType>([
    path(['scenes', 'messaging', 'messagingLogic']),
    actions({
        setTab: (tab: MessagingTab) => ({ tab }),
    }),
    reducers({
        currentTab: ['broadcasts' as MessagingTab, { setTab: (_, { tab }) => tab }],
    }),

    actionToUrl(({ values }) => ({
        setTab: () => [
            {
                broadcasts: urls.messagingBroadcasts(),
                providers: urls.messagingProviders(),
            }[values.currentTab] ?? urls.messagingBroadcasts(),
        ],
    })),
    urlToAction(({ actions, values }) => ({
        '/messaging/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setTab(tab as MessagingTab)
            }
        },
    })),
])

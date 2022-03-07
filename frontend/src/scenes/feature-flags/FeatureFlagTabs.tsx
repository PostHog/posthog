import React from 'react'
import { kea, useActions } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'

import { featureFlagTabsLogicType } from './FeatureFlagTabsType'
export enum FeatureFlagTab {
    Configuration = 'configuration',
    History = 'history',
}

const tabUrls: Record<FeatureFlagTab, (id: number) => string> = {
    [FeatureFlagTab.Configuration]: (id) => urls.featureFlag(id),
    [FeatureFlagTab.History]: (id) => urls.featureFlagHistory(id),
}

const featureFlagTabsLogic = kea<featureFlagTabsLogicType<FeatureFlagTab>>({
    path: ['scenes', 'feature-flags', 'featureFlagTabsLogic'],
    actions: {
        setTab: (tab: FeatureFlagTab, id: string | number) => ({ tab, id }),
    },
    reducers: {
        tab: [
            FeatureFlagTab.Configuration as FeatureFlagTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: () => ({
        setTab: ({ tab, id }) => tabUrls[tab as FeatureFlagTab](id),
    }),
    urlToAction: ({ actions, values }) => ({
        '/feature_flags/:id': ({ id }) => {
            if (id && FeatureFlagTab.Configuration !== values.tab) {
                actions.setTab(FeatureFlagTab.Configuration, id)
            }
        },
        '/feature_flags/:id/history': ({ id }) => {
            if (id && FeatureFlagTab.History !== values.tab) {
                actions.setTab(FeatureFlagTab.History, id)
            }
        },
    }),
})

export function FeatureFlagTabs({ tab, id }: { tab: FeatureFlagTab; id: string | number | null }): JSX.Element | null {
    const { setTab } = useActions(featureFlagTabsLogic)
    return id ? (
        <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={(t) => setTab(t as FeatureFlagTab, id)}>
            <Tabs.TabPane tab="Configuration" key="configuration" />
            <Tabs.TabPane tab={<span data-attr="feature-flag-history-tab">History</span>} key="history" />
        </Tabs>
    ) : null
}

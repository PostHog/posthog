import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import type { SceneTabKey } from '../../types'
import { type SceneTabConfig, scenesTabsLogic } from './scenesTabsLogic'

export function ScenesTabs(): JSX.Element {
    const { tabs, activeTab } = useValues(scenesTabsLogic)
    const { setTab } = useActions(scenesTabsLogic)

    return (
        <>
            <LemonBanner
                type="info"
                dismissKey="support-beta-banner"
                className="mb-4"
                action={{ children: 'Send feedback', id: 'support-feedback-button' }}
            >
                <p>
                    Support is in alpha. Please let us know what you'd like to see here and/or report any issues
                    directly to us!
                </p>
            </LemonBanner>
            <LemonTabs
                activeKey={activeTab}
                tabs={tabs.map((tab: SceneTabConfig) => ({
                    key: tab.key,
                    label: tab.label,
                }))}
                onChange={(key) => setTab(key as SceneTabKey)}
                sceneInset
            />
        </>
    )
}

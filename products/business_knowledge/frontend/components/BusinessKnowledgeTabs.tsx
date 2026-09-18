import { LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export type BusinessKnowledgeTab = 'sources' | 'settings'

export function BusinessKnowledgeTabs({ activeTab }: { activeTab: BusinessKnowledgeTab }): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeTab}
            sceneInset
            tabs={[
                {
                    key: 'sources',
                    label: 'Sources',
                    link: urls.businessKnowledge(),
                    // pinned: autocapture / Playwright key. Do not rename.
                    'data-attr': 'business-knowledge-tab-sources',
                },
                {
                    key: 'settings',
                    label: 'Settings',
                    link: urls.businessKnowledgeSettings(),
                    // pinned: autocapture / Playwright key. Do not rename.
                    'data-attr': 'business-knowledge-tab-settings',
                },
            ]}
        />
    )
}

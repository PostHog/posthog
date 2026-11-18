import { LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export type BusinessKnowledgeTab = 'sources' | 'usage' | 'playground' | 'settings'

export function BusinessKnowledgeTabs({ activeTab }: { activeTab: BusinessKnowledgeTab }): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeTab}
            sceneInset
            tabs={[
                {
                    key: 'sources',
                    label: 'Libraries',
                    link: urls.businessKnowledge(),
                    // pinned: autocapture / Playwright key. Do not rename.
                    'data-attr': 'business-knowledge-tab-sources',
                },
                {
                    key: 'usage',
                    label: 'Usage',
                    link: urls.businessKnowledgeUsage(),
                    // pinned: autocapture / Playwright key. Do not rename.
                    'data-attr': 'business-knowledge-tab-usage',
                },
                {
                    key: 'playground',
                    label: 'Playground',
                    link: urls.businessKnowledgePlayground(),
                    // pinned: autocapture / Playwright key. Do not rename.
                    'data-attr': 'business-knowledge-tab-playground',
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

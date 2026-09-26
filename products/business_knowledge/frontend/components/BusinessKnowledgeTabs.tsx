import { useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

export type BusinessKnowledgeTab = 'sources' | 'magic-eight-ball' | 'settings'

export function BusinessKnowledgeTabs({ activeTab }: { activeTab: BusinessKnowledgeTab }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const decisionsAvailable = !!featureFlags[FEATURE_FLAGS.ML_INFERENCE_DECISIONS] || !!preflight?.is_debug

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
                ...(decisionsAvailable
                    ? [
                          {
                              key: 'magic-eight-ball',
                              label: 'Magic 8 ball',
                              link: urls.businessKnowledgeMagicEightBall(),
                              'data-attr': 'business-knowledge-tab-magic-eight-ball',
                          },
                      ]
                    : []),
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

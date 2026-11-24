import type { ReactNode } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

function accessTab(sceneKey: Scene, link: string): { link?: string; disabledReason?: string } {
    const disabledReason = getProductAccessDisabledReason({ sceneKey })
    // LemonTabs still renders the link of a disabled tab, so a click would open the Access denied page.
    return { link: disabledReason ? undefined : link, disabledReason }
}

export function EvaluationsTabs({
    activeTab,
    children,
}: {
    activeTab: 'online-evals' | 'offline-evals' | 'scorers'
    children?: ReactNode
}): JSX.Element {
    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                data-attr="evaluations-tabs"
                sceneInset
                tabs={[
                    {
                        key: 'online-evals',
                        label: 'Online evals',
                        ...accessTab(Scene.AIObservabilityEvaluation, urls.aiObservabilityEvaluations()),
                        'data-attr': 'evaluations-tab',
                    },
                    {
                        key: 'offline-evals',
                        label: 'Offline evals',
                        ...accessTab(Scene.AIObservabilityOfflineExperiments, urls.aiObservabilityOfflineEvaluations()),
                        'data-attr': 'offline-evals-tab',
                    },
                    {
                        key: 'scorers',
                        label: 'Scorers',
                        ...accessTab(Scene.AIObservabilityScorers, urls.aiObservabilityScorers()),
                        'data-attr': 'llma-scorers-tab',
                    },
                    {
                        key: 'settings',
                        label: 'Settings',
                        link: urls.settings('project-ai-observability', 'ai-observability-byok'),
                        'data-attr': 'settings-tab',
                    },
                ]}
            />
            {children}
        </>
    )
}

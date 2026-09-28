import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function EvaluationsTabs({
    activeTab,
    children,
}: {
    activeTab: 'online-evals' | 'offline-evals' | 'scorers'
    children?: ReactNode
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

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
                        link: urls.aiObservabilityEvaluations(),
                        disabledReason: getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityEvaluation }),
                        'data-attr': 'evaluations-tab',
                    },
                    !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] && {
                        key: 'offline-evals',
                        label: 'Offline experiments',
                        link: urls.aiObservabilityOfflineEvaluations(),
                        disabledReason: getProductAccessDisabledReason({
                            sceneKey: Scene.AIObservabilityOfflineExperiments,
                        }),
                        'data-attr': 'offline-evals-tab',
                    },
                    {
                        key: 'scorers',
                        label: 'Scorers',
                        link: urls.aiObservabilityScorers(),
                        disabledReason: getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityScorers }),
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

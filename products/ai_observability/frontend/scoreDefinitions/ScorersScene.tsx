import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'

export function ScorersScene({ children }: { children: ReactNode }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Evaluations"
                description={
                    featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]
                        ? 'Manage score definitions and versions for manual reviews and offline evaluations.'
                        : 'Manage score definitions and versions for manual reviews.'
                }
                resourceType={{ type: 'llm_evaluations' }}
            />
            <EvaluationsTabs activeTab="scorers">{children}</EvaluationsTabs>
        </SceneContent>
    )
}

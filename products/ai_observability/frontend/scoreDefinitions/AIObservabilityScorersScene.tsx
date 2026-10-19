import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { AIObservabilityScoreDefinitions } from './AIObservabilityScoreDefinitions'

export const scene: SceneExport = { component: AIObservabilityScorersScene, productKey: ProductKey.AI_OBSERVABILITY }

export function AIObservabilityScorersScene(): JSX.Element {
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
            <EvaluationsTabs activeTab="scorers">
                <AIObservabilityScoreDefinitions />
            </EvaluationsTabs>
        </SceneContent>
    )
}

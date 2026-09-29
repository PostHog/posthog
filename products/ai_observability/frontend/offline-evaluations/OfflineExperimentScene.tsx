import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { OfflineExperimentContent } from './OfflineExperimentContent'

export const scene: SceneExport<{ experimentId: string }> = {
    component: OfflineExperimentScene,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { experimentId } }) => ({ experimentId }),
}

export function OfflineExperimentScene({ experimentId }: { experimentId: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    return (
        <SceneContent>
            <SceneTitleSection name="Offline experiment" resourceType={{ type: 'evaluation' }} />
            <EvaluationsTabs activeTab="offline-evals">
                {featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] && currentTeamId ? (
                    <OfflineExperimentContent
                        key={`${currentTeamId}:${experimentId}`}
                        teamId={currentTeamId}
                        experimentId={experimentId}
                    />
                ) : (
                    <LemonBanner type="info">Offline evals are not available for this project.</LemonBanner>
                )}
            </EvaluationsTabs>
        </SceneContent>
    )
}

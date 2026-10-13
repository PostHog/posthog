import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { OfflineEvaluationsGate } from './OfflineEvaluationsGate'
import { OfflineExperimentContent } from './OfflineExperimentContent'

export const scene: SceneExport<{ experimentId: string }> = {
    component: OfflineExperimentScene,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { experimentId } }) => ({ experimentId }),
}

export function OfflineExperimentScene({ experimentId }: { experimentId: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    return (
        <SceneContent>
            <SceneTitleSection name="Offline experiment" resourceType={{ type: 'evaluation' }} />
            <EvaluationsTabs activeTab="offline-evals">
                <OfflineEvaluationsGate isAvailable={!!currentTeamId}>
                    {currentTeamId && (
                        <OfflineExperimentContent
                            key={`${currentTeamId}:${experimentId}`}
                            teamId={currentTeamId}
                            experimentId={experimentId}
                        />
                    )}
                </OfflineEvaluationsGate>
            </EvaluationsTabs>
        </SceneContent>
    )
}

import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { OfflineEvaluationsGate } from './OfflineEvaluationsGate'
import { OfflineEvaluationsScene } from './OfflineEvaluationsScene'
import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'
import { OfflineExperimentContent } from './OfflineExperimentContent'

export const scene: SceneExport<{ experimentId: string }> = {
    component: OfflineExperimentScene,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { experimentId } }) => ({ experimentId }),
}

export function OfflineExperimentScene({ experimentId }: { experimentId: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    return (
        <OfflineEvaluationsScene>
            <div>
                <OfflineEvaluationsTabs activeTab="experiments" />
            </div>
            <OfflineEvaluationsGate isAvailable={!!currentTeamId}>
                {currentTeamId && (
                    <OfflineExperimentContent
                        key={`${currentTeamId}:${experimentId}`}
                        teamId={currentTeamId}
                        experimentId={experimentId}
                    />
                )}
            </OfflineEvaluationsGate>
        </OfflineEvaluationsScene>
    )
}

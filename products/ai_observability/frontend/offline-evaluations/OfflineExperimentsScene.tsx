import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { OfflineEvaluationsGate } from './OfflineEvaluationsGate'
import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'

export const scene: SceneExport = { component: OfflineExperimentsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function OfflineExperimentsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Evaluations"
                description="Follow score trends and inspect offline experiment results."
                resourceType={{ type: 'llm_evaluations' }}
            />
            <EvaluationsTabs activeTab="offline-evals">
                <OfflineEvaluationsGate
                    isAvailable={!!currentTeam && !!user}
                    unavailableMessage="Offline evaluations are not available in this project."
                >
                    {currentTeam && user && (
                        <OfflineExperimentsOverview
                            key={`${currentTeam.id}:${user.id}`}
                            teamId={currentTeam.id}
                            userId={user.id}
                            timezone={currentTeam.timezone}
                        />
                    )}
                </OfflineEvaluationsGate>
            </EvaluationsTabs>
        </SceneContent>
    )
}

import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'

export const scene: SceneExport = { component: OfflineExperimentsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function OfflineExperimentsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
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
                {featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] && currentTeam && user ? (
                    <OfflineExperimentsOverview
                        key={`${currentTeam.id}:${user.id}`}
                        teamId={currentTeam.id}
                        userId={user.id}
                        timezone={currentTeam.timezone}
                    />
                ) : (
                    <LemonBanner type="info">Offline evaluations are not available in this project.</LemonBanner>
                )}
            </EvaluationsTabs>
        </SceneContent>
    )
}

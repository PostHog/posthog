import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { AIObservabilityDatasetsScene } from '../datasets/AIObservabilityDatasetsScene'
import { offlineEvaluationsLogic } from './offlineEvaluationsLogic'
import { OfflineEvaluationsScene } from './OfflineEvaluationsScene'
import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'
import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'

export const scene: SceneExport = { component: OfflineExperimentsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function OfflineExperimentsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { activeTab, datasetsEnabled, offlineEvaluationsEnabled } = useValues(offlineEvaluationsLogic)
    const experimentsDisabledReason = !offlineEvaluationsEnabled
        ? 'Offline experiments are coming soon.'
        : getProductAccessDisabledReason({
              sceneKey: Scene.AIObservabilityOfflineExperiment,
              displayLabel: 'experiments',
          })
    const datasetsDisabledReason = !datasetsEnabled
        ? 'Datasets are coming soon.'
        : getProductAccessDisabledReason({
              sceneKey: Scene.AIObservabilityDatasets,
              displayLabel: 'datasets',
          })
    const activeTabDisabledReason =
        activeTab === 'datasets'
            ? datasetsDisabledReason
            : experimentsDisabledReason ||
              (!currentTeam || !user ? 'Offline evaluations are not available in this project.' : undefined)
    const navigation = <OfflineEvaluationsTabs activeTab={activeTab} />
    return (
        <OfflineEvaluationsScene>
            {activeTabDisabledReason ? (
                <>
                    {navigation}
                    <LemonBanner type="info">{activeTabDisabledReason}</LemonBanner>
                </>
            ) : activeTab === 'datasets' ? (
                <AIObservabilityDatasetsScene navigation={navigation} />
            ) : (
                currentTeam &&
                user && (
                    <OfflineExperimentsOverview
                        key={`${currentTeam.id}:${user.id}`}
                        teamId={currentTeam.id}
                        userId={user.id}
                        timezone={currentTeam.timezone}
                        navigation={navigation}
                    />
                )
            )}
        </OfflineEvaluationsScene>
    )
}

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AIObservabilityDatasetsScene } from '../datasets/AIObservabilityDatasetsScene'
import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { offlineEvaluationsLogic } from './offlineEvaluationsLogic'
import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'

export const scene: SceneExport = { component: OfflineExperimentsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function OfflineExperimentsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { activeTab, offlineEvaluationsEnabled } = useValues(offlineEvaluationsLogic)
    const { setActiveTab } = useActions(offlineEvaluationsLogic)
    const experimentsDisabledReason = !offlineEvaluationsEnabled
        ? 'Offline experiments are coming soon.'
        : getProductAccessDisabledReason({
              sceneKey: Scene.AIObservabilityOfflineExperiment,
              displayLabel: 'experiments',
          })
    const datasetsDisabledReason = getProductAccessDisabledReason({
        sceneKey: Scene.AIObservabilityDatasets,
        displayLabel: 'datasets',
    })
    const activeTabDisabledReason =
        activeTab === 'datasets'
            ? datasetsDisabledReason
            : experimentsDisabledReason ||
              (!currentTeam || !user ? 'Offline evaluations are not available in this project.' : undefined)
    const navigation = (
        <LemonSegmentedButton
            size="small"
            value={activeTab}
            onChange={setActiveTab}
            options={[
                {
                    value: 'experiments',
                    label: (
                        <span className="flex items-center gap-1">
                            <span>Experiments</span>
                            {!offlineEvaluationsEnabled && (
                                <LemonTag type="muted" size="small">
                                    Coming soon
                                </LemonTag>
                            )}
                        </span>
                    ),
                    disabledReason: experimentsDisabledReason,
                },
                { value: 'datasets', label: 'Datasets', disabledReason: datasetsDisabledReason },
            ]}
        />
    )
    return (
        <SceneContent>
            <SceneTitleSection
                name="Evaluations"
                description="Manage datasets, follow score trends, and inspect offline experiment results."
                resourceType={{ type: 'llm_evaluations' }}
            />
            <EvaluationsTabs activeTab="offline-evals">
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
            </EvaluationsTabs>
        </SceneContent>
    )
}

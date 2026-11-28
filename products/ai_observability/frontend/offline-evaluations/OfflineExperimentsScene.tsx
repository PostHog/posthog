import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { ProductEmptyStateGate } from 'lib/components/ProductEmptyState/ProductEmptyStateGate'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { AIObservabilityDatasetsScene } from '../datasets/AIObservabilityDatasetsScene'
import { datasetsEmptyState } from '../emptyState/datasetsEmptyState'
import { comparisonIds } from './offlineComparison'
import { offlineEvaluationsLogic } from './offlineEvaluationsLogic'
import { OfflineEvaluationsScene } from './OfflineEvaluationsScene'
import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'
import { OfflineExperimentComparison } from './OfflineExperimentComparison'
import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'

export const scene: SceneExport = { component: OfflineExperimentsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function OfflineExperimentsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { activeTab, datasetsEnabled } = useValues(offlineEvaluationsLogic)
    const { searchParams } = useValues(router)
    const { compare } = searchParams
    const scope = `${currentTeam?.id}:${user?.id}`
    const [lastComparison, setLastComparison] = useState<{ scope: string; ids: string[] } | null>(null)
    useEffect(() => {
        if (compare !== undefined) {
            setLastComparison({ scope, ids: comparisonIds(compare) })
        }
    }, [scope, compare])
    const experimentsDisabledReason = getProductAccessDisabledReason({
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
    const content = (
        <OfflineEvaluationsScene>
            {activeTabDisabledReason ? (
                <>
                    {navigation}
                    <LemonBanner type="info">{activeTabDisabledReason}</LemonBanner>
                </>
            ) : activeTab === 'datasets' ? (
                <AIObservabilityDatasetsScene navigation={navigation} />
            ) : searchParams.compare !== undefined && currentTeam ? (
                <>
                    {navigation}
                    <OfflineExperimentComparison
                        teamId={currentTeam.id}
                        experimentIds={comparisonIds(searchParams.compare)}
                        canOpenDatasets={!datasetsDisabledReason}
                    />
                </>
            ) : (
                currentTeam &&
                user && (
                    <OfflineExperimentsOverview
                        key={`${currentTeam.id}:${user.id}`}
                        teamId={currentTeam.id}
                        userId={user.id}
                        timezone={currentTeam.timezone}
                        navigation={navigation}
                        initialSelectedKeys={lastComparison?.scope === scope ? lastComparison.ids : undefined}
                    />
                )
            )}
        </OfflineEvaluationsScene>
    )

    return activeTab === 'datasets' && !activeTabDisabledReason ? (
        <ProductEmptyStateGate emptyState={datasetsEmptyState}>{content}</ProductEmptyStateGate>
    ) : (
        content
    )
}

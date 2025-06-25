import { actions, connect, kea, reducers, path } from 'kea'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SharedMetric } from './SharedMetrics/sharedMetricLogic'

import type { modalsLogicType } from './modalsLogicType'

export const modalsLogic = kea<modalsLogicType>([
    path(['scenes', 'experiments', 'modalsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], teamLogic, ['currentTeamId']],
        actions: [featureFlagsLogic, ['updateFlag']],
    })),
    actions({
        openExperimentCollectionGoalModal: true,
        closeExperimentCollectionGoalModal: true,
        openExposureCriteriaModal: true,
        closeExposureCriteriaModal: true,
        openShipVariantModal: true,
        closeShipVariantModal: true,
        openStopExperimentModal: true,
        closeStopExperimentModal: true,
        openEditConclusionModal: true,
        closeEditConclusionModal: true,
        openDistributionModal: true,
        closeDistributionModal: true,
        openReleaseConditionsModal: true,
        closeReleaseConditionsModal: true,
        openDescriptionModal: true,
        closeDescriptionModal: true,
        openStatsEngineModal: true,
        closeStatsEngineModal: true,
        openPrimaryMetricModal: (index: number) => ({ index }),
        closePrimaryMetricModal: true,
        openSecondaryMetricModal: (index: number) => ({ index }),
        closeSecondaryMetricModal: true,
        openPrimaryMetricSourceModal: true,
        closePrimaryMetricSourceModal: true,
        openSecondaryMetricSourceModal: true,
        closeSecondaryMetricSourceModal: true,
        openPrimarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closePrimarySharedMetricModal: true,
        openSecondarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closeSecondarySharedMetricModal: true,
        openVariantDeltaTimeseriesModal: true,
        closeVariantDeltaTimeseriesModal: true,
        openCalculateRunningTimeModal: true,
        closeCalculateRunningTimeModal: true,
    }),
    reducers({
        isExperimentCollectionGoalModalOpen: [
            false,
            {
                openExperimentCollectionGoalModal: () => true,
                closeExperimentCollectionGoalModal: () => false,
            },
        ],
        isExposureCriteriaModalOpen: [
            false,
            {
                openExposureCriteriaModal: () => true,
                closeExposureCriteriaModal: () => false,
            },
        ],
        isShipVariantModalOpen: [
            false,
            {
                openShipVariantModal: () => true,
                closeShipVariantModal: () => false,
            },
        ],
        isStopExperimentModalOpen: [
            false,
            {
                openStopExperimentModal: () => true,
                closeStopExperimentModal: () => false,
            },
        ],
        isEditConclusionModalOpen: [
            false,
            {
                openEditConclusionModal: () => true,
                closeEditConclusionModal: () => false,
            },
        ],
        isDistributionModalOpen: [
            false,
            {
                openDistributionModal: () => true,
                closeDistributionModal: () => false,
            },
        ],
        isReleaseConditionsModalOpen: [
            false,
            {
                openReleaseConditionsModal: () => true,
                closeReleaseConditionsModal: () => false,
            },
        ],
        isPrimaryMetricModalOpen: [
            false,
            {
                openPrimaryMetricModal: () => true,
                closePrimaryMetricModal: () => false,
            },
        ],
        isSecondaryMetricModalOpen: [
            false,
            {
                openSecondaryMetricModal: () => true,
                closeSecondaryMetricModal: () => false,
            },
        ],
        isPrimaryMetricSourceModalOpen: [
            false,
            {
                openPrimaryMetricSourceModal: () => true,
                closePrimaryMetricSourceModal: () => false,
            },
        ],
        isSecondaryMetricSourceModalOpen: [
            false,
            {
                openSecondaryMetricSourceModal: () => true,
                closeSecondaryMetricSourceModal: () => false,
            },
        ],
        isPrimarySharedMetricModalOpen: [
            false,
            {
                openPrimarySharedMetricModal: () => true,
                closePrimarySharedMetricModal: () => false,
            },
        ],
        isSecondarySharedMetricModalOpen: [
            false,
            {
                openSecondarySharedMetricModal: () => true,
                closeSecondarySharedMetricModal: () => false,
            },
        ],
        isVariantDeltaTimeseriesModalOpen: [
            false,
            {
                openVariantDeltaTimeseriesModal: () => true,
                closeVariantDeltaTimeseriesModal: () => false,
            },
        ],
        isCalculateRunningTimeModalOpen: [
            false,
            {
                openCalculateRunningTimeModal: () => true,
                closeCalculateRunningTimeModal: () => false,
            },
        ],
        isDescriptionModalOpen: [
            false,
            {
                openDescriptionModal: () => true,
                closeDescriptionModal: () => false,
            },
        ],
        isStatsEngineModalOpen: [
            false,
            {
                openStatsEngineModal: () => true,
                closeStatsEngineModal: () => false,
            },
        ],
    }),
])

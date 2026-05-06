import { actions, kea, path, reducers } from 'kea'

import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import type { legacyExperimentModalsLogicType } from './legacyExperimentModalsLogicType'

/**
 * @deprecated
 * This logic manages modal state for legacy experiments (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * For modern experiments, use modalsLogic.
 *
 * Only includes modals that legacy experiments actually use:
 * - Description editing
 * - Conclusion editing
 * - Stats engine viewing
 * - Shared metric management
 * - Custom metric viewing (read-only)
 * - Metric source selection
 *
 * Does NOT include (modern experiment only):
 * - Collection goal modal
 * - Conclusion editing modal
 * - Exposure criteria modal
 * - Distribution modal
 * - Release conditions modal
 * - Running time calculator modal
 * - Metrics reorder modals
 * - Finish/Pause/Resume experiment modals (these are shared from main logic)
 * - Variant delta timeseries modal
 */
export const legacyExperimentModalsLogic = kea<legacyExperimentModalsLogicType>([
    path(['scenes', 'experiments', 'legacy', 'legacyExperimentModalsLogic']),
    actions({
        // Shared metrics - Primary
        openPrimarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closePrimarySharedMetricModal: true,

        // Shared metrics - Secondary
        openSecondarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closeSecondarySharedMetricModal: true,

        // Custom metrics - Primary (read-only viewing)
        openPrimaryMetricModal: (uuid: string) => ({ uuid }),
        closePrimaryMetricModal: true,

        // Custom metrics - Secondary (read-only viewing)
        openSecondaryMetricModal: (uuid: string) => ({ uuid }),
        closeSecondaryMetricModal: true,

        // Metric source selection - Primary
        openPrimaryMetricSourceModal: true,
        closePrimaryMetricSourceModal: true,

        // Metric source selection - Secondary
        openSecondaryMetricSourceModal: true,
        closeSecondaryMetricSourceModal: true,
    }),
    reducers({
        // Primary shared metric modal state
        isPrimarySharedMetricModalOpen: [
            false,
            {
                openPrimarySharedMetricModal: () => true,
                closePrimarySharedMetricModal: () => false,
            },
        ],

        // Secondary shared metric modal state
        isSecondarySharedMetricModalOpen: [
            false,
            {
                openSecondarySharedMetricModal: () => true,
                closeSecondarySharedMetricModal: () => false,
            },
        ],

        // Primary metric modal state (read-only)
        isPrimaryMetricModalOpen: [
            false,
            {
                openPrimaryMetricModal: () => true,
                closePrimaryMetricModal: () => false,
            },
        ],

        // Secondary metric modal state (read-only)
        isSecondaryMetricModalOpen: [
            false,
            {
                openSecondaryMetricModal: () => true,
                closeSecondaryMetricModal: () => false,
            },
        ],

        // Primary metric source modal state
        isPrimaryMetricSourceModalOpen: [
            false,
            {
                openPrimaryMetricSourceModal: () => true,
                closePrimaryMetricSourceModal: () => false,
            },
        ],

        // Secondary metric source modal state
        isSecondaryMetricSourceModalOpen: [
            false,
            {
                openSecondaryMetricSourceModal: () => true,
                closeSecondaryMetricSourceModal: () => false,
            },
        ],
    }),
])

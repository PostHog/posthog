import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import {
    LegacyExploreButton,
    LegacyResultsQuery,
    LegacySummaryTable,
    LegacyWinningVariantText,
    LegacySignificanceText,
} from '~/scenes/experiments/legacy'
import type { Experiment } from '~/types'

interface LegacyChartModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentTrendsQuery | ExperimentFunnelsQuery
    displayOrder: number
    isSecondary: boolean
    result: any
    experiment: Experiment
}

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyChartModal({
    isOpen,
    onClose,
    metric,
    displayOrder,
    isSecondary,
    result,
    experiment,
}: LegacyChartModalProps): JSX.Element {
    // Get metric uuid from experiment metrics array using displayOrder
    const metricsList = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricUuid = metricsList[displayOrder]?.uuid || ''

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1200}
            title="Metric results"
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <div className="flex justify-end">
                <LegacyExploreButton result={result} />
            </div>
            <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                <div className="items-center inline-flex flex-wrap">
                    <LegacyWinningVariantText result={result} />
                    <LegacySignificanceText metricUuid={metricUuid} isSecondary={isSecondary} />
                </div>
            </LemonBanner>
            <LegacySummaryTable metric={metric} displayOrder={displayOrder} isSecondary={isSecondary} />
            <LegacyResultsQuery result={result} showTable={true} />
        </LemonModal>
    )
}

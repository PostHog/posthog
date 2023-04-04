import { useMountedLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import {
    FunnelCorrelationSkewWarning,
    FunnelCorrelationSkewWarningDataExploration,
} from './FunnelCorrelationSkewWarning'
import { FunnelCorrelationTable, FunnelCorrelationTableDataExploration } from './FunnelCorrelationTable'
import { FunnelCorrelationFeedbackForm } from './FunnelCorrelationFeedbackForm'
import { FunnelPropertyCorrelationTable } from './FunnelPropertyCorrelationTable'
import { AvailableFeature } from '~/types'

import './FunnelCorrelation.scss'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps, isUsingDataExploration } = useValues(insightLogic)
    const { steps: legacySteps } = useValues(funnelLogic(insightProps))
    const { steps } = useValues(funnelDataLogic(insightProps))
    useMountedLogic(funnelCorrelationUsageLogic(insightProps))

    if (isUsingDataExploration ? steps.length <= 1 : legacySteps.length <= 1) {
        return null
    }

    return (
        <>
            <h2 className="my-4">Correlation analysis</h2>
            <PayGateMini feature={AvailableFeature.CORRELATION_ANALYSIS}>
                <div className="funnel-correlation">
                    {isUsingDataExploration ? (
                        <FunnelCorrelationSkewWarningDataExploration />
                    ) : (
                        <FunnelCorrelationSkewWarning />
                    )}
                    {isUsingDataExploration ? <FunnelCorrelationTableDataExploration /> : <FunnelCorrelationTable />}
                    <FunnelCorrelationFeedbackForm />
                    {!isUsingDataExploration && <FunnelPropertyCorrelationTable />}
                </div>
            </PayGateMini>
        </>
    )
}

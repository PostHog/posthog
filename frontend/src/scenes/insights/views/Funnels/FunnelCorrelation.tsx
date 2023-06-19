import { useMountedLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FunnelCorrelationSkewWarning } from './FunnelCorrelationSkewWarning'
import { FunnelCorrelationTable } from './FunnelCorrelationTable'
import { FunnelCorrelationFeedbackForm } from './FunnelCorrelationFeedbackForm'
import { FunnelPropertyCorrelationTable } from './FunnelPropertyCorrelationTable'
import { AvailableFeature } from '~/types'

import './FunnelCorrelation.scss'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { steps } = useValues(funnelDataLogic(insightProps))
    useMountedLogic(funnelCorrelationUsageLogic(insightProps))

    if (steps.length <= 1) {
        return null
    }

    return (
        <>
            <h2 className="my-4">Correlation analysis</h2>
            <PayGateMini feature={AvailableFeature.CORRELATION_ANALYSIS}>
                <div className="funnel-correlation">
                    <FunnelCorrelationSkewWarning />
                    <FunnelCorrelationTable />
                    <FunnelCorrelationFeedbackForm />
                    <FunnelPropertyCorrelationTable />
                </div>
            </PayGateMini>
        </>
    )
}

import './FunnelCorrelation.scss'

import { useMountedLogic, useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { AvailableFeature, FunnelVizType } from '~/types'

import { FunnelCorrelationSkewWarning } from './FunnelCorrelationSkewWarning'
import { FunnelCorrelationTable } from './FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './FunnelPropertyCorrelationTable'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { steps, funnelVizType: vizType, hasDataWarehouseSeries } = useValues(funnelDataLogic(insightProps))
    useMountedLogic(funnelCorrelationUsageLogic(insightProps))
    if (
        (vizType !== FunnelVizType.Steps && vizType !== FunnelVizType.Flow) ||
        steps.length <= 1 ||
        hasDataWarehouseSeries
    ) {
        return null
    }

    return (
        <>
            <h2 className="font-semibold text-lg my-4">Correlation analysis</h2>
            <PayGateMini feature={AvailableFeature.CORRELATION_ANALYSIS} featureDetail="funnel-correlation-analysis">
                <div className="funnel-correlation">
                    <FunnelCorrelationSkewWarning />
                    <FunnelCorrelationTable />
                    <FunnelPropertyCorrelationTable />
                </div>
            </PayGateMini>
        </>
    )
}

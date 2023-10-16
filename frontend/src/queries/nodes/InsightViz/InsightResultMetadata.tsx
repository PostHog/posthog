import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizLogic } from 'scenes/insights/insightVizLogic'

import { ComputationTimeWithRefresh } from './ComputationTimeWithRefresh'

type InsightResultMetadataProps = {
    disableLastComputation?: boolean
    disableLastComputationRefresh?: boolean
}

export const InsightResultMetadata = ({
    disableLastComputation,
    disableLastComputationRefresh,
}: InsightResultMetadataProps): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { samplingFactor } = useValues(insightVizLogic(insightProps))
    return (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className="text-muted-alt">
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
        </>
    )
}

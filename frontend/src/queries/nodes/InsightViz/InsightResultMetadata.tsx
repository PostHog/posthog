import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

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
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    return (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className="text-secondary">
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
        </>
    )
}

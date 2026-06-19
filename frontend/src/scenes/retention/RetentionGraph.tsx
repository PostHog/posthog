import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartDisplayType } from '~/types'

import { RetentionBarChart } from 'products/product_analytics/frontend/insights/retention/RetentionBarChart/RetentionBarChart'
import { RetentionLineChart } from 'products/product_analytics/frontend/insights/retention/RetentionLineChart/RetentionLineChart'

import { retentionGraphLogic } from './retentionGraphLogic'

interface RetentionGraphProps {
    inSharedMode?: boolean
}

export function RetentionGraph({ inSharedMode = false }: RetentionGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionGraphLogic(insightProps))

    const isBarDisplay = retentionFilter?.display === ChartDisplayType.ActionsBar
    if (isBarDisplay) {
        return <RetentionBarChart inSharedMode={inSharedMode} />
    }
    return <RetentionLineChart inSharedMode={inSharedMode} />
}

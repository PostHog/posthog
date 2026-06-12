import './InsightLegend.scss'

import clsx from 'clsx'
import { useValues } from 'kea'

import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'

import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightLegendRow } from './InsightLegendRow'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { indexedResults, hasLegend } = useValues(trendsDataLogic(insightProps))

    return hasLegend ? (
        <div
            className={clsx('InsightLegendMenu', 'flex overflow-auto border rounded', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="grid grid-cols-1">
                {indexedResults &&
                    indexedResults.map((item) => <InsightLegendRow key={item.id} item={item} readOnly={readOnly} />)}
            </div>
        </div>
    ) : null
}

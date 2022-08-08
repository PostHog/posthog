import { useValues } from 'kea'
import React from 'react'

import { ChartParams } from '~/types'
import { insightLogic } from '../../insightLogic'
import { Textfit } from 'react-textfit'

import './BoldNumber.scss'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function BoldNumber({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insight, filters, insightLoading } = useValues(insightLogic)

    const value = insight.result[0].aggregated_value

    return !insightLoading ? (
        <Textfit mode="single" min={32} max={256}>
            <div
                className="BoldNumber"
                style={filters.font !== '-system' ? { fontFamily: filters.font || 'Comic Sans MS' } : undefined}
            >
                {formatAggregationAxisValue(filters.aggregation_axis_format, value)}
            </div>
        </Textfit>
    ) : (
        <Spinner size="lg" />
    )
}

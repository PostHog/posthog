import { useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from './funnelLogic'

export function FunnelHistogram(): JSX.Element {
    const { timeConversionBins } = useValues(funnelLogic)
    const labels = timeConversionBins.map((bin) => humanFriendlyDuration(`${bin[0]}`))
    const binData = timeConversionBins.map((bin) => bin[1])
    const dataset = [{ data: binData, labels: labels, label: 'Time to convert', count: 3 }]
    return (
        <LineGraph
            data-attr="funnels-histogram"
            type="bar"
            color={'white'}
            datasets={dataset}
            labels={labels}
            dashboardItemId={null}
        />
    )
}

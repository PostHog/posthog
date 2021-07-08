import { useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from './funnelLogic'

export function FunnelHistogram(): JSX.Element {
    // const { timeToConvert } = useValues(funnelLogic)
    const timeToConvert = [[2220.0, 2], [29080.0, 0], [55940.0, 0], [82800.0, 1]]
    const labels = timeToConvert.map(bin => humanFriendlyDuration(`${bin[0]}`))
    const binData = timeToConvert.map(bin => bin[1])
    const dataset = [{data: binData, labels: labels, label: 'Time to convert', count: 3}]
    
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
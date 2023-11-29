import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconShowChart, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'

export const TableDisplay = (): JSX.Element => {
    const { setVisualizationDisplayType } = useActions(dataNodeLogic.findMounted())
    const { visualizationDisplayType } = useValues(dataNodeLogic.findMounted())

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            options: [
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                },
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconShowChart />,
                    label: 'Line chart',
                },
            ],
        },
    ]

    return (
        <LemonSelect
            key="2"
            value={visualizationDisplayType || ChartDisplayType.ActionsTable}
            onChange={(value) => {
                setVisualizationDisplayType(value)
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={options}
            size="small"
        />
    )
}

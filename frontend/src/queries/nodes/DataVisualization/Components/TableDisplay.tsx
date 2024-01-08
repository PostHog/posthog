import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconBarChart, IconShowChart, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const TableDisplay = (): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { visualizationType } = useValues(dataVisualizationLogic)

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
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconBarChart />,
                    label: 'Bar chart',
                },
            ],
        },
    ]

    return (
        <LemonSelect
            value={visualizationType}
            onChange={(value) => {
                setVisualizationType(value)
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

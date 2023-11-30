import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { IconShowChart, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const TableDisplay = (): JSX.Element => {
    const logic = useMountedLogic(dataVisualizationLogic)
    const { setVisualizationType } = useActions(logic)
    const { visualizationType } = useValues(logic)

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

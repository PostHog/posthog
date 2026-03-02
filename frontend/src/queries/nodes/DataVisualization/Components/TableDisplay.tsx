import { useActions, useValues } from 'kea'

import { IconGraph, IconLifecycle, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from '@posthog/lemon-ui'

import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableDisplayProps extends Pick<LemonSelectProps<ChartDisplayType>, 'disabledReason'> {}

export const TableDisplay = ({ disabledReason }: TableDisplayProps): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { autoVisualizationType, hasDateTimeColumns, visualizationType } = useValues(dataVisualizationLogic)

    const displayTypeLabels: Record<ChartDisplayType, string> = {
        [ChartDisplayType.Auto]: 'Auto',
        [ChartDisplayType.ActionsLineGraph]: 'Line chart',
        [ChartDisplayType.ActionsBar]: 'Bar chart',
        [ChartDisplayType.ActionsUnstackedBar]: 'Unstacked bar chart',
        [ChartDisplayType.ActionsStackedBar]: 'Stacked bar chart',
        [ChartDisplayType.ActionsAreaGraph]: 'Area chart',
        [ChartDisplayType.ActionsLineGraphCumulative]: 'Cumulative line chart',
        [ChartDisplayType.BoldNumber]: 'Big number',
        [ChartDisplayType.ActionsPie]: 'Pie chart',
        [ChartDisplayType.ActionsBarValue]: 'Value chart',
        [ChartDisplayType.ActionsTable]: 'Table',
        [ChartDisplayType.WorldMap]: 'World map',
        [ChartDisplayType.CalendarHeatmap]: 'Calendar heatmap',
        [ChartDisplayType.TwoDimensionalHeatmap]: '2d heatmap',
    }

    const renderDisplayTypeLabel = (displayType: ChartDisplayType): string => {
        const selectedLabel = displayTypeLabels[displayType] ?? displayType

        if (displayType !== ChartDisplayType.Auto) {
            return selectedLabel
        }

        const resolvedLabel = displayTypeLabels[autoVisualizationType] ?? autoVisualizationType
        return `Auto (${resolvedLabel})`
    }

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Auto',
            options: [
                {
                    value: ChartDisplayType.Auto,
                    icon: <IconTrends />,
                    label: renderDisplayTypeLabel(ChartDisplayType.Auto),
                },
            ],
        },
        {
            title: 'Table',
            options: [
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                },
                {
                    value: ChartDisplayType.BoldNumber,
                    icon: <Icon123 />,
                    label: 'Big Number',
                },
            ],
        },
        {
            title: 'Charts',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconTrends />,
                    label: 'Line chart',
                    disabledReason: !hasDateTimeColumns ? 'Requires a date or datetime column' : undefined,
                },
                {
                    value: ChartDisplayType.ActionsBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                },
                {
                    value: ChartDisplayType.ActionsStackedBar,
                    icon: <IconLifecycle />,
                    label: 'Stacked bar chart',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                    disabledReason: !hasDateTimeColumns ? 'Requires a date or datetime column' : undefined,
                },
                {
                    value: ChartDisplayType.TwoDimensionalHeatmap,
                    icon: <IconHeatmap />,
                    label: '2d heatmap',
                },
            ],
        },
    ]

    return (
        <LemonSelect
            disabledReason={disabledReason}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType)}
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

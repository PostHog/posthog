import { useValues } from 'kea'
import { ClockCircleOutlined, LineChartOutlined, FunnelPlotOutlined } from '@ant-design/icons'
import { FunnelsFilterType, FunnelVizType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'
import { insightLogic } from 'scenes/insights/insightLogic'

type ToggleButtonChartFilterProps = {
    setFilter: (filter: FunnelsFilterType) => void
} & FunnelsFilterType

export function ToggleButtonChartFilter({
    funnel_viz_type,
    setFilter,
}: ToggleButtonChartFilterProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelLogic(insightProps))

    const options = [
        {
            key: FunnelVizType.Steps,
            label: 'Conversion steps',
            description: `Track ${aggregationTargetLabel.plural} progress between steps of the funnel`,
            icon: <FunnelPlotOutlined />,
        },
        {
            key: FunnelVizType.TimeToConvert,
            label: 'Time to convert',
            description: `Track how long it takes for ${aggregationTargetLabel.plural} to convert`,
            icon: <ClockCircleOutlined />,
        },
        {
            key: FunnelVizType.Trends,
            label: 'Historical trends',
            description: "Track how this funnel's conversion rate is trending over time",
            icon: <LineChartOutlined />,
        },
    ]

    return (
        <div className="funnel-chart-filter">
            <DropdownSelector
                options={options}
                value={funnel_viz_type || FunnelVizType.Steps}
                onValueChange={(val) => {
                    const valueTyped = val as FunnelVizType

                    if (funnel_viz_type !== valueTyped) {
                        setFilter({ funnel_viz_type: valueTyped })
                    }
                }}
                hideDescriptionOnDisplay
                compact
            />
        </div>
    )
}

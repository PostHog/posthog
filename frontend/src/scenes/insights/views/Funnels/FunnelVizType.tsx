import { ClockCircleOutlined, LineChartOutlined, FunnelPlotOutlined } from '@ant-design/icons'
import { FunnelsFilterType, FunnelVizType as VizType } from '~/types'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'
import { Noun } from '~/models/groupsModel'

type FunnelVizTypeProps = {
    setFilter: (filter: FunnelsFilterType) => void
    aggregationTargetLabel: Noun
} & FunnelsFilterType

export function FunnelVizType({
    funnel_viz_type,
    setFilter,
    aggregationTargetLabel,
}: FunnelVizTypeProps): JSX.Element | null {
    const options = [
        {
            key: VizType.Steps,
            label: 'Conversion steps',
            description: `Track ${aggregationTargetLabel.plural} progress between steps of the funnel`,
            icon: <FunnelPlotOutlined />,
        },
        {
            key: VizType.TimeToConvert,
            label: 'Time to convert',
            description: `Track how long it takes for ${aggregationTargetLabel.plural} to convert`,
            icon: <ClockCircleOutlined />,
        },
        {
            key: VizType.Trends,
            label: 'Historical trends',
            description: "Track how this funnel's conversion rate is trending over time",
            icon: <LineChartOutlined />,
        },
    ]

    return (
        <div className="funnel-chart-filter">
            <DropdownSelector
                options={options}
                value={funnel_viz_type || VizType.Steps}
                onValueChange={(val) => {
                    const valueTyped = val as VizType

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

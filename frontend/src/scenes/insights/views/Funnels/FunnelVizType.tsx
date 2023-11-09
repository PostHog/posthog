import { useActions, useValues } from 'kea'
// eslint-disable-next-line no-restricted-imports
import { ClockCircleOutlined, LineChartOutlined } from '@ant-design/icons'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelVizType as VizType, EditorFilterProps } from '~/types'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'
import { FunnelsFilter } from '~/queries/schema'
import { IconFunnels } from '@posthog/icons'

export function FunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnel_viz_type } = (insightFilter || {}) as FunnelsFilter

    const options = [
        {
            key: VizType.Steps,
            label: 'Conversion steps',
            description: `Track ${aggregationTargetLabel.plural} progress between steps of the funnel`,
            icon: <IconFunnels />,
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
                        updateInsightFilter({ funnel_viz_type: valueTyped })
                    }
                }}
                hideDescriptionOnDisplay
                compact
            />
        </div>
    )
}

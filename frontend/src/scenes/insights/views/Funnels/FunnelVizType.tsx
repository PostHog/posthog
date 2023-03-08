import { useActions, useValues } from 'kea'
import { ClockCircleOutlined, LineChartOutlined, FunnelPlotOutlined } from '@ant-design/icons'

import { Noun } from '~/models/groupsModel'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { EditorFilterProps, FunnelsFilterType, FunnelVizType as VizType, QueryEditorFilterProps } from '~/types'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'

export function FunnelVizTypeDataExploration({
    insightProps,
}: Pick<QueryEditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <FunnelVizTypeComponent
            aggregationTargetLabel={aggregationTargetLabel}
            setFilter={updateInsightFilter}
            {...insightFilter}
        />
    )
}

export function FunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel } = useValues(funnelLogic(insightProps))
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return (
        <FunnelVizTypeComponent aggregationTargetLabel={aggregationTargetLabel} setFilter={setFilters} {...filters} />
    )
}

type FunnelVizTypeComponentProps = {
    setFilter: (filter: FunnelsFilterType) => void
    aggregationTargetLabel: Noun
} & FunnelsFilterType

function FunnelVizTypeComponent({
    funnel_viz_type,
    setFilter,
    aggregationTargetLabel,
}: FunnelVizTypeComponentProps): JSX.Element | null {
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

import { IconClock, IconFilter, IconTrending } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema'
import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

type LabelProps = {
    icon: JSX.Element
    title: string
}
const Label = ({ icon, title }: LabelProps): JSX.Element => (
    <div className="flex items-center text-sm font-medium gap-1">
        {icon} {title}
    </div>
)

type LabelInMenuProps = {
    icon: JSX.Element
    title: string
    description: string
}
const LabelInMenu = ({ icon, title, description }: LabelInMenuProps): JSX.Element => (
    <div>
        <div className="flex items-center text-sm font-medium gap-1">
            {icon} {title}
        </div>
        <div className="text-muted text-xs mt-1">{description}</div>
    </div>
)

export function FunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnel_viz_type } = (insightFilter || {}) as FunnelsFilter

    const options = [
        {
            value: VizType.Steps,
            label: <Label icon={<IconFilter className="text-muted" />} title="Conversion steps" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconFilter className="text-muted" />}
                    title="Conversion steps"
                    description={`Track ${aggregationTargetLabel.plural} progress between steps of the funnel`}
                />
            ),
        },
        {
            value: VizType.TimeToConvert,
            label: <Label icon={<IconClock className="text-muted" />} title="Time to convert" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconClock className="text-muted" />}
                    title="Time to convert"
                    description={`Track how long it takes for ${aggregationTargetLabel.plural} to convert`}
                />
            ),
        },
        {
            value: VizType.Trends,
            label: <Label icon={<IconTrending className="text-muted" />} title="Historical trends" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconTrending className="text-muted" />}
                    title="Historical trends"
                    description="Track how this funnel's conversion rate is trending over time"
                />
            ),
        },
    ]

    return (
        <LemonSelect
            size="small"
            value={funnel_viz_type || VizType.Steps}
            onChange={(value) => {
                if (funnel_viz_type !== value) {
                    updateInsightFilter({ funnel_viz_type: value })
                }
            }}
            options={options}
            dropdownMatchSelectWidth={false}
        />
    )
}

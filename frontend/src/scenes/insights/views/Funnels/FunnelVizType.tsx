import { useActions, useValues } from 'kea'

import { IconClock, IconFilter, IconTrending } from '@posthog/icons'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
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
        <div className="text-secondary text-xs mt-1">{description}</div>
    </div>
)

export function FunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel, series } = useValues(funnelDataLogic(insightProps))
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelVizType } = (insightFilter || {}) as FunnelsFilter

    if (funnelVizType === VizType.Flow) {
        return null
    }

    // Optional steps are only supported in "Conversion steps" (see ValidateOptionalFunnelSteps on the backend) -
    // disable the other graph types instead of letting the query fail after the fact.
    const hasOptionalSteps = !!series?.some((step) => step.optionalInFunnel)
    const optionalStepsDisabledReason = hasOptionalSteps
        ? 'Not supported with optional steps. Remove the optional steps first.'
        : undefined

    const options = [
        {
            value: VizType.Steps,
            label: <Label icon={<IconFilter className="text-secondary" />} title="Conversion steps" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconFilter className="text-secondary" />}
                    title="Conversion steps"
                    description={`Track ${aggregationTargetLabel.plural} progress between steps of the funnel`}
                />
            ),
        },
        {
            value: VizType.TimeToConvert,
            label: <Label icon={<IconClock className="text-secondary" />} title="Time to convert" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconClock className="text-secondary" />}
                    title="Time to convert"
                    description={`Track how long it takes for ${aggregationTargetLabel.plural} to convert`}
                />
            ),
            disabledReason: optionalStepsDisabledReason,
        },
        {
            value: VizType.Trends,
            label: <Label icon={<IconTrending className="text-secondary" />} title="Historical trends" />,
            labelInMenu: (
                <LabelInMenu
                    icon={<IconTrending className="text-secondary" />}
                    title="Historical trends"
                    description="Track how this funnel's conversion rate is trending over time"
                />
            ),
            disabledReason: optionalStepsDisabledReason,
        },
    ]

    return (
        <LemonSelect
            size="small"
            value={funnelVizType || VizType.Steps}
            onChange={(value) => {
                if (funnelVizType !== value) {
                    updateInsightFilter({ funnelVizType: value })
                }
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-viz-type-select"
        />
    )
}

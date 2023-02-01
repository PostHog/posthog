import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelLayout } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'
import { IconFunnelHorizontal, IconFunnelVertical } from 'lib/lemon-ui/icons'
import { FunnelsFilter } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelDisplayLayoutPickerDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return <FunnelDisplayLayoutPickerComponent {...insightFilter} setFilters={updateInsightFilter} />
}

export function FunnelDisplayLayoutPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return <FunnelDisplayLayoutPickerComponent {...filters} setFilters={setFilters} />
}

type FunnelDisplayLayoutPickerComponentProps = {
    setFilters: (filters: FunnelsFilter) => void
} & FunnelsFilter

export function FunnelDisplayLayoutPickerComponent({
    layout,
    setFilters,
}: FunnelDisplayLayoutPickerComponentProps): JSX.Element {
    const options = [
        {
            title: 'Graph Display Options',
            options: [
                {
                    value: FunnelLayout.vertical,
                    icon: <IconFunnelVertical />,
                    label: 'Left to right',
                },
                {
                    value: FunnelLayout.horizontal,
                    icon: <IconFunnelHorizontal />,
                    label: 'Top to bottom',
                },
            ],
        },
    ]

    return (
        <LemonSelect
            value={layout || FunnelLayout.vertical}
            onChange={(layout: FunnelLayout | null) => layout && setFilters({ layout })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            options={options}
            size="small"
        />
    )
}

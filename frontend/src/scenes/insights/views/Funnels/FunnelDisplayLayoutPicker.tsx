import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelLayout } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'
import { IconFunnelHorizontal, IconFunnelVertical } from 'lib/lemon-ui/icons'

export function FunnelDisplayLayoutPicker({ disabled }: { disabled?: boolean }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { barGraphLayout } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

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
            value={barGraphLayout || FunnelLayout.vertical}
            onChange={(layout: FunnelLayout | null) => layout && setFilters({ layout })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            disabled={disabled}
            options={options}
            size="small"
        />
    )
}

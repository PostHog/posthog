import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'
import { IconFunnelHorizontal, IconFunnelVertical } from 'lib/lemon-ui/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelDisplayLayoutPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

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
            value={funnelsFilter?.layout || FunnelLayout.vertical}
            onChange={(layout: FunnelLayout | null) => layout && updateInsightFilter({ layout })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            options={options}
            size="small"
        />
    )
}

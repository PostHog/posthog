import { useActions, useValues } from 'kea'

import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { FunnelLayout } from 'lib/constants'
import { IconFunnelHorizontal, IconFunnelVertical } from 'lib/lemon-ui/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

const OPTIONS = [
    { value: FunnelLayout.vertical, icon: <IconFunnelVertical />, label: 'Left to right' },
    { value: FunnelLayout.horizontal, icon: <IconFunnelHorizontal />, label: 'Top to bottom' },
]

const ITEMS = Object.fromEntries(
    OPTIONS.map((option) => [
        option.value,
        <span className="flex items-center gap-2" key={option.value}>
            {option.icon}
            {option.label}
        </span>,
    ])
)

export function FunnelDisplayLayoutPickerNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <Select
            value={funnelsFilter?.layout || FunnelLayout.vertical}
            items={ITEMS}
            onValueChange={(layout: string | null) => {
                if (layout) {
                    updateInsightFilter({ layout: layout as FunnelLayout })
                }
            }}
            disabled={!!editingDisabledReason}
        >
            <SelectTrigger
                size="sm"
                data-quill
                data-attr="funnel-bar-layout-selector"
                title={editingDisabledReason ?? undefined}
            >
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel>Graph display options</SelectGroupLabel>
                    {OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.icon}
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}

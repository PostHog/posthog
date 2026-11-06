import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ChartOptionLabel } from './ChartOptionLabel'
import type { ChartOptionChoice } from './ChartOptionSelect'
import { QuillChartOptionToggleGroup } from './QuillChartOptionToggleGroup'

export interface ChartOptionToggleGroupProps<T extends string | number> {
    /** Without a label the choices fill the row, for a group whose heading already names it. */
    label?: string
    info?: string
    value: T
    options: ChartOptionChoice<T>[]
    onChange: (value: T) => void
    disabledReason?: string | null
    'data-attr'?: string
}

export function ChartOptionToggleGroup<T extends string | number>(props: ChartOptionToggleGroupProps<T>): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillChartOptionToggleGroup {...props} />
    }

    const { label, info, value, options, onChange, disabledReason, 'data-attr': dataAttr } = props
    return (
        <div className="flex flex-col gap-1" data-attr={dataAttr}>
            {label && <ChartOptionLabel label={label} info={info} />}
            <LemonSegmentedButton<T>
                size="small"
                fullWidth
                value={value}
                options={options}
                onChange={(next) => onChange(next)}
                disabledReason={disabledReason ?? undefined}
            />
        </div>
    )
}

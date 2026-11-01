import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ChartOptionLabel } from './ChartOptionLabel'
import { QuillChartOptionSwitch } from './QuillChartOptionSwitch'

export interface ChartOptionSwitchProps {
    label: string
    info?: string
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string | null
    'data-attr'?: string
}

export function ChartOptionSwitch(props: ChartOptionSwitchProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillChartOptionSwitch {...props} />
    }

    const { label, info, checked, onChange, disabledReason, 'data-attr': dataAttr } = props
    return (
        <LemonSwitch
            fullWidth
            // Full-width switches pad their label to line up with buttons; here it lines up with the other labels.
            className="!px-0"
            label={<ChartOptionLabel label={label} info={info} />}
            checked={checked}
            onChange={onChange}
            disabledReason={disabledReason}
            data-attr={dataAttr}
        />
    )
}

import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

import type { PoeFilterControlProps } from './PoeFilter'

export function QuillPoeFilter({ checked, onChange, disabledReason }: PoeFilterControlProps): JSX.Element {
    return (
        <QuillLabeledSwitch
            checked={checked}
            onChange={onChange}
            label="Use person properties from query time"
            tooltip="Overrides the default person property mode for this insight to use query-time person properties instead of event-time properties. This can be useful when person data is updated after the event, but it can also slow queries significantly."
            disabledReason={disabledReason}
        />
    )
}

import { LemonDisabledArea, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import type { PoeFilterControlProps } from './PoeFilter'

export function LemonPoeFilter({ checked, onChange, disabledReason }: PoeFilterControlProps): JSX.Element {
    return (
        <LemonDisabledArea className="flex items-center gap-1 w-fit" disabledReason={disabledReason}>
            <LemonLabel
                info="Overrides the default person property mode for this insight to use query-time person properties instead of event-time properties. This can be useful when person data is updated after the event, but it can also slow queries significantly."
                infoLink="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
            >
                Use person properties from query time
            </LemonLabel>
            <LemonSwitch className="m-2" disabled={!!disabledReason} onChange={onChange} checked={checked} />
        </LemonDisabledArea>
    )
}

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

interface LemonEventNamePropsWithoutAllEvents {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
    placeholder?: string
    /** By default "All events" is not allowed. */
    allEventsOption?: never
}
interface LemonEventNamePropsWithAllEvents {
    value: string | null
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
    /** Allow "All events", in either explicit option item form, or clear button form. */
    allEventsOption: 'explicit' | 'clear'
}
export function LemonEventName({
    value,
    onChange,
    disabled,
    placeholder = 'Select an event',
    allEventsOption,
}: LemonEventNamePropsWithAllEvents | LemonEventNamePropsWithoutAllEvents): JSX.Element {
    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            disabled={disabled}
            value={value as string}
            type="secondary"
            placeholder={placeholder}
            data-attr="event-name-box"
            renderValue={(v) =>
                v !== null ? <PropertyKeyInfo value={v} disablePopover type={TaxonomicFilterGroupType.Events} /> : null
            }
            allowClear={allEventsOption === 'clear'}
            excludedProperties={allEventsOption !== 'explicit' ? { events: [null] } : undefined}
            size="small"
        />
    )
}

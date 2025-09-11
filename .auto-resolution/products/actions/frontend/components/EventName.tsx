import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

interface EventNamePropsWithoutAllEvents {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
    placeholder?: string
    /** By default "All events" is not allowed. */
    allEventsOption?: never
}
interface EventNamePropsWithAllEvents {
    value: string | null
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
    /** Allow "All events", in either explicit option item form, or clear button form. */
    allEventsOption: 'explicit' | 'clear'
}
export function EventName({
    value,
    onChange,
    disabled,
    placeholder = 'Select an event',
    allEventsOption,
    ...props
}: (EventNamePropsWithAllEvents | EventNamePropsWithoutAllEvents) &
    Pick<TaxonomicPopoverProps, 'placement'>): JSX.Element {
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
            {...props}
        />
    )
}

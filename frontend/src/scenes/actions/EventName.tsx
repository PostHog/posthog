import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonTaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface LemonEventNamePropsWithAllEvents {
    value: string | null
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
    includeAllEventsOption: true
}
interface LemonEventNamePropsWithoutAllEvents {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
    placeholder?: string
    includeAllEventsOption?: false
}
export function LemonEventName({
    value,
    onChange,
    disabled,
    placeholder = 'Select an event',
    includeAllEventsOption,
}: LemonEventNamePropsWithAllEvents | LemonEventNamePropsWithoutAllEvents): JSX.Element {
    return (
        <LemonTaxonomicPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            disabled={disabled}
            value={value as string}
            type="secondary"
            status="stealth"
            placeholder={placeholder}
            dataAttr="event-name-box"
            renderValue={(v) => (v !== null ? <PropertyKeyInfo value={v} disablePopover /> : null)}
            excludedProperties={!includeAllEventsOption ? { events: [null] } : undefined}
        />
    )
}

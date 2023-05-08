import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonTaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface EventNameInterface {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
    placeholder?: string
}
export function LemonEventName({ value, onChange, disabled, placeholder }: EventNameInterface): JSX.Element {
    return (
        <LemonTaxonomicStringPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            disabled={disabled}
            value={value}
            type="secondary"
            status="stealth"
            placeholder={placeholder ?? 'Select an event'}
            dataAttr="event-name-box"
            renderValue={(v) => <PropertyKeyInfo value={v} disablePopover />}
            excludedProperties={{ events: [null] }}
            allowClear
        />
    )
}

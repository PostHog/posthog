import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonTaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface LemonEventNameProps {
    value: string | null
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
}
export function LemonEventName({
    value,
    onChange,
    disabled,
    placeholder = 'Select an event',
}: LemonEventNameProps): JSX.Element {
    return (
        <LemonTaxonomicPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            disabled={disabled}
            value={value}
            type="secondary"
            status="stealth"
            placeholder={placeholder}
            dataAttr="event-name-box"
            renderValue={(v) => (v !== null ? <PropertyKeyInfo value={v} disablePopover /> : null)}
        />
    )
}

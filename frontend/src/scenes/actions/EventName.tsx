import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonTaxonomicStringPopover, TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface EventNameInterface {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
}

export function EventName({ value, onChange }: EventNameInterface): JSX.Element {
    return (
        <TaxonomicStringPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            value={value}
            type="secondary"
            style={{ maxWidth: '24rem' }}
            placeholder="Choose an event"
            dataAttr="event-name-box"
            renderValue={(v) => <PropertyKeyInfo value={v} disablePopover />}
            allowClear
        />
    )
}

export function LemonEventName({ value, onChange, disabled }: EventNameInterface): JSX.Element {
    return (
        <LemonTaxonomicStringPopover
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            disabled={disabled}
            value={value}
            type="secondary"
            status="stealth"
            placeholder="Select an event"
            dataAttr="event-name-box"
            renderValue={(v) => <PropertyKeyInfo value={v} disablePopover />}
            allowClear
        />
    )
}

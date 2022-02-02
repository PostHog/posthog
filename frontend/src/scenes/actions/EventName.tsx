import React from 'react'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface EventNameInterface {
    value: string
    onChange: (value: string) => void
}

export function EventName({ value, onChange }: EventNameInterface): JSX.Element {
    return (
        <TaxonomicPopup
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            value={value}
            style={{ width: '100%', maxWidth: '24rem' }}
            placeholder="Choose an event"
            dataAttr="event-name-box"
            renderValue={(v) => <PropertyKeyInfo value={v} />}
        />
    )
}

import React, { CSSProperties } from 'react'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicStringPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface EventNameInterface {
    value: string
    onChange: (value: string) => void
    style?: CSSProperties
}

export function EventName({ value, onChange, style }: EventNameInterface): JSX.Element {
    return (
        <TaxonomicStringPopup
            groupType={TaxonomicFilterGroupType.Events}
            onChange={onChange}
            value={value}
            style={{ maxWidth: '24rem', ...style }}
            placeholder="Choose an event"
            dataAttr="event-name-box"
            renderValue={(v) => <PropertyKeyInfo value={v} />}
        />
    )
}

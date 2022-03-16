import React, { useState } from 'react'
import { TaxonomicPopup, TaxonomicStringPopup } from '../TaxonomicPopup'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useMountedLogic } from 'kea'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__stories__/mocks'

export default {
    title: 'Filters/TaxonomicPopup',
    decorators: [taxonomicFilterMocksDecorator],
}

export const TaxonomicStringPopupOneCategory = (): JSX.Element => {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)
    const [value, setValue] = useState<string | undefined>('$browser')

    return (
        <TaxonomicStringPopup
            groupType={TaxonomicFilterGroupType.PersonProperties}
            value={value}
            onChange={setValue}
            renderValue={(v) => <PropertyKeyInfo value={v} />}
        />
    )
}

export const MultipleCategories = (): JSX.Element => {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)
    const [value, setValue] = useState<string | number | undefined>(undefined)
    const [group, setGroup] = useState(TaxonomicFilterGroupType.PersonProperties)

    return (
        <TaxonomicPopup
            groupType={group}
            value={value}
            onChange={(v, g) => {
                setValue(v)
                setGroup(g)
            }}
            groupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
            ]}
        />
    )
}

import React, { useState } from 'react'
import { TaxonomicPopup, TaxonomicStringPopup } from './TaxonomicPopup'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useMountedLogic } from 'kea'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { ComponentMeta } from '@storybook/react'

export default {
    title: 'Filters/TaxonomicPopup',
    component: TaxonomicPopup,
    decorators: [taxonomicFilterMocksDecorator],
} as ComponentMeta<typeof TaxonomicPopup>

export function TaxonomicStringPopupOneCategory(): JSX.Element {
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

export function MultipleCategories(): JSX.Element {
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
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Cohorts,
            ]}
        />
    )
}

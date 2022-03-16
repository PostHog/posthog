import React, { useState } from 'react'
import { TaxonomicPopup, TaxonomicStringPopup } from '../TaxonomicPopup'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { defaultFilterMocks } from 'lib/components/TaxonomicFilter/__stories__/mocks'
import { KeaStory } from 'storybook/kea-story'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export default {
    title: 'Filters/TaxonomicPopup',
}

export const TaxonomicStringPopupOneCategory = (): JSX.Element => {
    const [value, setValue] = useState<string | undefined>('$browser')

    return (
        <KeaStory
            onInit={() => {
                personPropertiesModel.mount()
                cohortsModel.mount()
                defaultFilterMocks()
            }}
        >
            <TaxonomicStringPopup
                groupType={TaxonomicFilterGroupType.PersonProperties}
                value={value}
                onChange={setValue}
                renderValue={(v) => <PropertyKeyInfo value={v} />}
            />
        </KeaStory>
    )
}

export const MultipleCategories = (): JSX.Element => {
    const [value, setValue] = useState<string | number | undefined>(undefined)
    const [group, setGroup] = useState(TaxonomicFilterGroupType.PersonProperties)

    return (
        <KeaStory
            onInit={() => {
                personPropertiesModel.mount()
                cohortsModel.mount()
                defaultFilterMocks()
            }}
        >
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
        </KeaStory>
    )
}

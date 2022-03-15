import React from 'react'
import { TaxonomicFilter } from '../TaxonomicFilter'
import { Provider } from 'kea'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { defaultFilterMocks } from 'lib/components/TaxonomicFilter/__stories__/mocks'
import { resetKeaStory } from 'storybook/kea-story'

export default {
    title: 'Filters/TaxonomicFilter',
}

export const AllGroups = (): JSX.Element => {
    resetKeaStory()

    personPropertiesModel.mount()
    cohortsModel.mount()
    defaultFilterMocks()

    return (
        <Provider>
            <TaxonomicFilter
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                ]}
            />
        </Provider>
    )
}

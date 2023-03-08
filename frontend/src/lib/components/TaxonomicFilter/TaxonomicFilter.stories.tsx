import { TaxonomicFilter } from './TaxonomicFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic } from 'kea'

export default {
    title: 'Filters',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        testOptions: { skip: true }, // FIXME: This is currently excluded due to flaky loading of data in it
    },
}

export function TaxonomicFilter_(): JSX.Element {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)

    return (
        <TaxonomicFilter
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Cohorts,
            ]}
        />
    )
}

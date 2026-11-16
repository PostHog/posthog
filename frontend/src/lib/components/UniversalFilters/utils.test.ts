import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { EntityTypes } from '~/types'

import { taxonomicFilterGroupTypeToEntityType } from './utils'

describe('taxonomicFilterGroupTypeToEntityType', () => {
    it.each([
        [TaxonomicFilterGroupType.Events, EntityTypes.EVENTS],
        [TaxonomicFilterGroupType.Actions, EntityTypes.ACTIONS],
        [TaxonomicFilterGroupType.DataWarehouse, EntityTypes.DATA_WAREHOUSE],
    ])('maps %s to %s', (input, expected) => {
        expect(taxonomicFilterGroupTypeToEntityType(input)).toBe(expected)
    })

    it.each([
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Cohorts,
    ])('returns null for unmapped type %s', (input) => {
        expect(taxonomicFilterGroupTypeToEntityType(input)).toBeNull()
    })
})

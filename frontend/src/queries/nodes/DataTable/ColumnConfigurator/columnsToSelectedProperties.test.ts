import { SelectedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    taxonomicEventFilterToHogQL,
    taxonomicPersonFilterToHogQL,
    taxonomicSessionFilterToHogQL,
} from '~/queries/utils'

import { ColumnToHogQL, columnsToSelectedProperties } from './columnsToSelectedProperties'

describe('columnsToSelectedProperties', () => {
    const cases: [
        string,
        { columns: string[]; taxonomicGroupTypes: TaxonomicFilterGroupType[]; toHogQL: ColumnToHogQL },
        SelectedProperties,
    ][] = [
        [
            'event, feature flag and person columns of an events table',
            {
                columns: [
                    'event',
                    'properties.$browser',
                    'properties."odd name"',
                    'properties."$feature/my-flag"',
                    'person.properties.email',
                    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                    'timestamp',
                ],
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                toHogQL: taxonomicEventFilterToHogQL,
            },
            {
                [TaxonomicFilterGroupType.EventProperties]: ['$browser', 'odd name', '$feature/my-flag'],
                [TaxonomicFilterGroupType.EventFeatureFlags]: ['$browser', 'odd name', '$feature/my-flag'],
                [TaxonomicFilterGroupType.PersonProperties]: ['email'],
            },
        ],
        [
            'only the prefixed person columns of a persons table',
            {
                columns: ['person_display_name -- Person', 'id', 'properties.email', 'created_at'],
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties],
                toHogQL: taxonomicPersonFilterToHogQL,
            },
            { [TaxonomicFilterGroupType.PersonProperties]: ['email'] },
        ],
    ]

    it.each(cases)('marks %s', (_name, input, expected) => {
        expect(columnsToSelectedProperties(input)).toEqual(expected)
    })

    it('marks the prefixed and the bare session columns of a sessions table', () => {
        expect(
            columnsToSelectedProperties({
                columns: ['$is_bounce', 'session.$entry_current_url', 'person.properties.email'],
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SessionProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
                toHogQL: taxonomicSessionFilterToHogQL,
                implicitPrefixGroupType: TaxonomicFilterGroupType.SessionProperties,
            })
        ).toEqual({
            [TaxonomicFilterGroupType.SessionProperties]: ['$is_bounce', '$entry_current_url'],
            [TaxonomicFilterGroupType.PersonProperties]: ['email'],
        })
    })
})

import { breakdownForField, fieldForBreakdown } from './filterBarBreakdownFields'
import { FilterBarField } from './filterBarTypes'

const cohortName = (id: number): string | undefined => (id === 7 ? 'Power users' : undefined)

describe('filterBarBreakdownFields', () => {
    it.each<[string, FilterBarField, Record<string, unknown>]>([
        [
            'event property',
            { categoryId: 'event_properties', key: '$browser', label: 'Browser' },
            { breakdown_type: 'event', breakdown: '$browser' },
        ],
        [
            'group property',
            { categoryId: 'group_properties_2', key: 'plan', label: 'plan' },
            { breakdown_type: 'group', breakdown: 'plan', breakdown_group_type_index: 2 },
        ],
        [
            'cohort',
            { categoryId: 'cohorts', key: '7', label: 'Power users' },
            { breakdown_type: 'cohort', breakdown: [7] },
        ],
        [
            'url',
            { categoryId: 'event_properties', key: '$current_url', label: 'Current URL' },
            { breakdown_type: 'event', breakdown: '$current_url', breakdown_normalize_url: true },
        ],
    ])('round-trips a %s breakdown', (_, field, expected) => {
        const breakdownFilter = breakdownForField(field)
        expect(breakdownFilter).toMatchObject(expected)
        expect(fieldForBreakdown(breakdownFilter, cohortName)).toMatchObject({
            categoryId: field.categoryId,
            key: field.key,
            label: field.label,
        })
    })

    it('reads the first entry of a multiple-breakdowns filter', () => {
        expect(fieldForBreakdown({ breakdowns: [{ property: 'email', type: 'person' }] }, cohortName)).toMatchObject({
            categoryId: 'person_properties',
            key: 'email',
        })
    })

    it('reads no field from an empty breakdown', () => {
        expect(fieldForBreakdown({ breakdown_type: 'event', breakdown: null }, cohortName)).toBeNull()
    })
})

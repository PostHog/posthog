import { getCohortIdentifier, getCohortSaveDisabledReason } from './saveAsTargets'

describe('SQL cohort eligibility', () => {
    const current = { isDirectConnection: false, isMultiQuery: false, hasCurrentResults: true }
    it.each([
        { name: 'person ID', columns: ['person_id'], expected: 'person_id' },
        { name: 'actor ID', columns: ['actor_id'], expected: 'actor_id' },
        {
            name: 'distinct ID with an unrelated ID',
            columns: ['id', 'distinct_id'],
            tables: ['events'],
            expected: 'distinct_id',
        },
        { name: 'ID from persons', columns: ['id'], tables: ['posthog.persons'], expected: 'id' },
        { name: 'ambiguous ID across tables', columns: ['id'], tables: ['events', 'persons'], expected: undefined },
        { name: 'ID without current table metadata', columns: ['id'], expected: undefined },
        { name: 'ambiguous person IDs', columns: ['person_id', 'person_id'], expected: undefined },
        { name: 'unrelated column', columns: ['count'], expected: undefined },
    ])('$name', ({ columns, tables, expected }) => {
        const identifier = getCohortIdentifier(columns, tables)
        expect(identifier).toBe(expected)
        expect(getCohortSaveDisabledReason({ ...current, identifier }) === undefined).toBe(!!expected)
    })

    it.each([{ hasCurrentResults: false }, { isMultiQuery: true }, { isDirectConnection: true }])(
        'rejects a person ID result when %j',
        (state) => {
            expect(getCohortSaveDisabledReason({ ...current, ...state, identifier: 'person_id' })).toBeTruthy()
        }
    )
})

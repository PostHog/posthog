import { getCohortSaveDisabledReason } from './saveAsTargets'

describe('SQL cohort eligibility', () => {
    const current = { isDirectConnection: false, isMultiQuery: false, hasCurrentResults: true }
    it.each([
        { name: 'person ID', columns: ['person_id'], eligible: true },
        { name: 'actor ID', columns: ['actor_id'], eligible: true },
        { name: 'distinct ID', columns: ['event', 'distinct_id'], eligible: true },
        { name: 'ID from persons', columns: ['id'], tables: ['posthog.persons'], eligible: true },
        { name: 'ambiguous ID across tables', columns: ['id'], tables: ['events', 'persons'], eligible: false },
        { name: 'ID without current table metadata', columns: ['id'], eligible: false },
        { name: 'unrelated column', columns: ['count'], eligible: false },
    ])('$name', ({ columns, tables, eligible }) => {
        expect(getCohortSaveDisabledReason({ ...current, columns, tables }) === undefined).toBe(eligible)
    })

    it.each([{ hasCurrentResults: false }, { isMultiQuery: true }, { isDirectConnection: true }])(
        'rejects a person ID result when %j',
        (state) => {
            expect(getCohortSaveDisabledReason({ ...current, ...state, columns: ['person_id'] })).toBeTruthy()
        }
    )
})

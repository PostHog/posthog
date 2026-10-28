import { PREDICTIONS_PEOPLE_LIMIT, PREDICTIONS_PEOPLE_VIEWS, predictionsPeopleQuery } from './predictionsPeopleQuery'

describe('predictionsPeopleQuery', () => {
    test.each(PREDICTIONS_PEOPLE_VIEWS.map(({ value }) => value))(
        '%s reads display names only for the top people, never joining persons over the batch',
        (view) => {
            const query = predictionsPeopleQuery(view).replace(/\s+/g, ' ')

            expect(query).not.toMatch(/JOIN persons\b/i)
            expect(query).toContain(`LIMIT ${PREDICTIONS_PEOPLE_LIMIT} ), names AS`)
            expect(query).toContain('FROM raw_persons WHERE id IN (SELECT toUUID(person_id) FROM top)')
            expect(query).toContain('FROM top t LEFT JOIN names n')
        }
    )
})

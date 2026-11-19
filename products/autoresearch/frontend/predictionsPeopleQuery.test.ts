import {
    PREDICTIONS_PEOPLE_LIMIT,
    PREDICTIONS_PEOPLE_VIEWS,
    PredictionsPeopleView,
    predictionsPeopleFooter,
    predictionsPeopleQuery,
} from './predictionsPeopleQuery'

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

    test.each<[PredictionsPeopleView, number, string]>([
        ['most_likely', 12345, 'Top 50 of 12,345 people by score'],
        ['biggest_movers', 2000, 'Top 50 of 2,000 people by change in score'],
        ['least_likely', 2000, 'Bottom 50 of 2,000 people by score'],
        ['most_likely', 50, 'All 50 people by score'],
        ['most_likely', 1, '1 person by score'],
    ])('the %s footer for %d scored people reads "%s"', (view, scoredPeople, expected) => {
        expect(predictionsPeopleFooter(view, scoredPeople)).toEqual(expected)
    })
})

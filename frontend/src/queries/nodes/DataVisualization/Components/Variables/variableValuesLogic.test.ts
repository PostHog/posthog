import { performQuery } from '~/queries/query'

import { ListVariable } from '../../types'
import {
    MAX_LIST_VARIABLE_OPTIONS,
    loadListVariableOptions,
    queryResultsToVariableOptions,
} from './variableValuesLogic'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const queryVariable: ListVariable = {
    id: 'variable-id',
    name: 'Event names',
    code_name: 'event_names',
    type: 'List',
    values: [],
    default_value: [],
    is_multi: true,
    values_query: 'SELECT event, count() FROM events GROUP BY event',
}

describe('variableValuesLogic', () => {
    it('uses unique scalar values from the first query result column', () => {
        expect(
            queryResultsToVariableOptions([
                ['pageview', 10],
                ['signup', 5],
                ['pageview', 3],
                [42, 1],
                [null, 1],
                [{ unsupported: true }, 1],
            ])
        ).toEqual([
            { value: 'pageview', label: '10' },
            { value: 'signup', label: '5' },
            { value: '42', label: '1' },
        ])
    })

    it('falls back to the value as label when the second column is not scalar', () => {
        expect(queryResultsToVariableOptions([['pageview'], ['signup', { unsupported: true }]])).toEqual([
            { value: 'pageview', label: 'pageview' },
            { value: 'signup', label: 'signup' },
        ])
    })

    it('runs the configured HogQL query under a row limit that clears the HogQL default', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [['pageview'], ['signup']] })

        await expect(loadListVariableOptions(queryVariable)).resolves.toEqual({
            options: [
                { value: 'pageview', label: 'pageview' },
                { value: 'signup', label: 'signup' },
            ],
            truncated: false,
        })
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: 'SELECT * FROM (\nSELECT event, count() FROM events GROUP BY event\n) AS variable_values LIMIT 2001',
        })
    })

    it('runs the query against the configured connection', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [['pageview']] })

        await loadListVariableOptions({ ...queryVariable, values_query_connection_id: 'connection-uuid' })
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: expect.stringContaining('LIMIT 2001'),
            connectionId: 'connection-uuid',
        })
    })

    it('drops a trailing semicolon so the row limit wrapper stays valid', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [] })

        await loadListVariableOptions({ ...queryVariable, values_query: 'SELECT event FROM events;' })
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: 'SELECT * FROM (\nSELECT event FROM events\n) AS variable_values LIMIT 2001',
        })
    })

    // A value the options query returns past HogQL's 100-row default was unreachable in the
    // dropdown, and search for it answered "No options matching".
    it.each([
        ['every row loads below the ceiling', 150, 150, false],
        ['rows past the ceiling are reported as cut', MAX_LIST_VARIABLE_OPTIONS + 1, MAX_LIST_VARIABLE_OPTIONS, true],
    ])('%s', async (_name, rowCount, expectedOptions, expectedTruncated) => {
        jest.mocked(performQuery).mockResolvedValue({
            results: Array.from({ length: rowCount }, (_, index) => [`value-${index}`]),
        })

        const { options, truncated } = await loadListVariableOptions(queryVariable)

        expect(options).toHaveLength(expectedOptions)
        expect(truncated).toBe(expectedTruncated)
    })

    // The fallback runs the query as written, so a LIMIT of its own can return more rows than the
    // ceiling the dropdown holds.
    it.each([
        ['a full default page is reported as cut', 100, 100],
        ['rows past the ceiling are still capped', MAX_LIST_VARIABLE_OPTIONS + 1, MAX_LIST_VARIABLE_OPTIONS],
    ])('a query the wrapper cannot hold: %s', async (_name, rowCount, expectedOptions) => {
        jest.mocked(performQuery)
            .mockRejectedValueOnce(new Error('Syntax error'))
            .mockResolvedValueOnce({ results: Array.from({ length: rowCount }, (_, index) => [`value-${index}`]) })

        const { options, truncated } = await loadListVariableOptions(queryVariable)

        expect(options).toHaveLength(expectedOptions)
        expect(truncated).toBe(true)
        expect(performQuery).toHaveBeenLastCalledWith({
            kind: 'HogQLQuery',
            query: queryVariable.values_query,
        })
    })
})

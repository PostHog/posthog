import { performQuery } from '~/queries/query'

import { ListVariable } from '../../types'
import {
    MAX_LIST_VARIABLE_OPTIONS,
    loadListVariableOptions,
    queryResultsToVariableOptions,
    withOptionsRowLimit,
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

    it('runs the configured HogQL query to load options', async () => {
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
            query: withOptionsRowLimit(queryVariable.values_query!, MAX_LIST_VARIABLE_OPTIONS + 1),
        })
    })

    it('runs the query against the configured connection', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [['pageview']] })

        await loadListVariableOptions({ ...queryVariable, values_query_connection_id: 'connection-uuid' })
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: withOptionsRowLimit(queryVariable.values_query!, MAX_LIST_VARIABLE_OPTIONS + 1),
            connectionId: 'connection-uuid',
        })
    })

    // HogQL gives a query without its own LIMIT 100 rows, which hid every later value from the
    // dropdown and from its search.
    it('loads values that sit past the HogQL default row limit', async () => {
        const rows = Array.from({ length: 150 }, (_, index) => [`school-${index}`])
        jest.mocked(performQuery).mockResolvedValue({ results: rows })

        const { options, truncated } = await loadListVariableOptions(queryVariable)

        expect(options).toHaveLength(150)
        expect(options).toContainEqual({ value: 'school-149', label: 'school-149' })
        expect(truncated).toBe(false)
    })

    it('reports truncation when the query has more rows than the dropdown holds', async () => {
        const rows = Array.from({ length: MAX_LIST_VARIABLE_OPTIONS + 1 }, (_, index) => [`value-${index}`])
        jest.mocked(performQuery).mockResolvedValue({ results: rows })

        const { options, truncated } = await loadListVariableOptions(queryVariable)

        expect(options).toHaveLength(MAX_LIST_VARIABLE_OPTIONS)
        expect(truncated).toBe(true)
    })

    it('keeps a query the row limit wrapper cannot hold working', async () => {
        jest.mocked(performQuery)
            .mockRejectedValueOnce(new Error('Syntax error'))
            .mockResolvedValueOnce({ results: [['pageview']] })

        await expect(loadListVariableOptions(queryVariable)).resolves.toEqual({
            options: [{ value: 'pageview', label: 'pageview' }],
            truncated: false,
        })
        expect(performQuery).toHaveBeenLastCalledWith({
            kind: 'HogQLQuery',
            query: queryVariable.values_query,
        })
    })

    it('drops a trailing semicolon so the row limit wrapper stays valid', () => {
        expect(withOptionsRowLimit('SELECT event FROM events;\n', 10)).toBe(
            'SELECT * FROM (\nSELECT event FROM events\n) AS variable_values LIMIT 10'
        )
    })
})

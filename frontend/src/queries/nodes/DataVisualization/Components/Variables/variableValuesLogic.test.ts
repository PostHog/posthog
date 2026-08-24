import { performQuery } from '~/queries/query'

import { ListVariable } from '../../types'
import { loadListVariableOptions, queryResultsToVariableOptions } from './variableValuesLogic'

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

        await expect(loadListVariableOptions(queryVariable)).resolves.toEqual([
            { value: 'pageview', label: 'pageview' },
            { value: 'signup', label: 'signup' },
        ])
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: queryVariable.values_query,
        })
    })

    it('runs the query against the configured connection', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [['pageview']] })

        await loadListVariableOptions({ ...queryVariable, values_query_connection_id: 'connection-uuid' })
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: queryVariable.values_query,
            connectionId: 'connection-uuid',
        })
    })
})

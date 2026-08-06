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
        ).toEqual(['pageview', 'signup', '42'])
    })

    it('runs the configured HogQL query to load options', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [['pageview'], ['signup']] })

        await expect(loadListVariableOptions(queryVariable)).resolves.toEqual(['pageview', 'signup'])
        expect(performQuery).toHaveBeenCalledWith({
            kind: 'HogQLQuery',
            query: queryVariable.values_query,
        })
    })
})

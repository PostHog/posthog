import { NotebookNodeSQLV2Result, toCachedResults } from './NotebookNodeSQLV2'

describe('NotebookNodeSQLV2', () => {
    const resultTyped = (type: string): NotebookNodeSQLV2Result => ({
        columns: ['total'],
        types: [['total', type]],
        row_count: 1,
        first_page: [[7]],
    })

    // A saved cell can hold pandas dtypes from the sandbox kernel. Charts read these names to
    // find a numeric axis, so a stored 'float64' must resolve without a re-run of the cell.
    it.each([
        ['float64', 'Float64'],
        ['int64', 'Int64'],
        ['uint8', 'Int64'],
        ['bool', 'Bool'],
        ['datetime64[ns, UTC]', 'DateTime'],
        ['str', 'String'],
        ['object', 'String'],
        ['Nullable(Int64)', 'Nullable(Int64)'],
    ])('names a %s column %s', (stored, expected) => {
        expect(toCachedResults(resultTyped(stored)).types).toEqual([['total', expected]])
    })
})

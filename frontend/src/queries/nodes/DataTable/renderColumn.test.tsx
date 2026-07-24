import { getContextColumn } from './renderColumn'

describe('getContextColumn', () => {
    it.each([[undefined], [null]])(
        'returns an empty result without throwing when key is %p',
        (key: string | null | undefined) => {
            // A malformed columns array can surface an undefined column name; guard against
            // `key.startsWith is not a function` crashing the whole DataTable render.
            expect(getContextColumn(key as unknown as string)).toEqual({
                queryContextColumnName: undefined,
                queryContextColumn: undefined,
            })
        }
    )

    it('resolves a context column key against the provided columns', () => {
        const column = { title: 'Sentiment' }
        expect(getContextColumn('context.columns.sentiment', { sentiment: column })).toEqual({
            queryContextColumnName: 'sentiment',
            queryContextColumn: column,
        })
    })

    it('returns no context column for a plain key', () => {
        expect(getContextColumn('timestamp')).toEqual({
            queryContextColumnName: undefined,
            queryContextColumn: undefined,
        })
    })
})

import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'
import {
    NotebookVariable,
    extractSqlVariableReferences,
    getNotebookVariableConflictNames,
    getNotebookVariableErrors,
    getRunnableNotebookVariables,
    getSavableNotebookVariables,
    parseNotebookVariables,
} from './notebookVariables'

describe('notebookVariables', () => {
    const country: NotebookVariable = { name: 'country', type: 'string', value: 'US' }

    describe('extractSqlVariableReferences', () => {
        it.each([
            ['a placeholder', 'select 1 where c = {country}', ['country']],
            ['each name once', 'select {a}, {a}, {b}', ['a', 'b']],
            // A name mentioned in prose or an example must not mark the cell stale, nor bind.
            ['not inside a line comment', '-- see {country}\nselect 1', []],
            ['not inside a string literal', "select '{country}' as label", []],
            ['not a dotted chain', 'select {variables.country}', []],
            ['not a struct literal', "select {'a': 1}", []],
        ])('finds %s', (_name, sql, expected) => {
            expect(extractSqlVariableReferences(sql)).toEqual(expected)
        })
    })

    describe('parseNotebookVariables', () => {
        it('reads the notebook column', () => {
            expect(
                parseNotebookVariables([
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'lookback_days', type: 'number', value: 30 },
                ])
            ).toEqual([
                { name: 'country', type: 'string', value: 'US' },
                { name: 'lookback_days', type: 'number', value: 30 },
            ])
        })

        it.each([
            ['null', null],
            ['a non-array', { name: 'country' }],
        ])('returns nothing for %s', (_name, value) => {
            expect(parseNotebookVariables(value)).toEqual([])
        })

        it('drops a malformed entry without losing its neighbours', () => {
            // The column is plain JSON the API can write, so one bad entry must not blank the bar.
            expect(parseNotebookVariables(['nonsense', { name: 'country', type: 'string', value: 'US' }])).toEqual([
                country,
            ])
        })

        it('coerces a value that does not match its declared type', () => {
            expect(parseNotebookVariables([{ name: 'days', type: 'number', value: '30' }])).toEqual([
                { name: 'days', type: 'number', value: 30 },
            ])
        })
    })

    describe('getNotebookVariableErrors', () => {
        it.each([
            ['an empty name', '', 'Give the variable a name.'],
            ['a hyphen', 'look-back', 'Use letters, numbers, and underscores.'],
            ['a leading digit', '7days', "The name can't start with a number."],
            // HogQL injects its own {filters}, so a variable could never be read under that name.
            ['the reserved filters name', 'filters', 'reserved'],
        ])('rejects %s', (_name, variableName, expected) => {
            const [error] = getNotebookVariableErrors([{ name: variableName, type: 'string', value: '' }])
            expect(error).toContain(expected)
        })

        it('rejects the second of two declarations sharing a name', () => {
            const errors = getNotebookVariableErrors([country, { ...country, value: 'DE' }])
            expect(errors[0]).toBeNull()
            expect(errors[1]).toContain('already declared')
        })

        it("rejects a name a cell's output dataframe already uses", () => {
            // Both land in one kernel namespace, so sharing a name means one clobbers the other.
            const errors = getNotebookVariableErrors(
                [{ name: 'sql_df', type: 'string', value: 'US' }],
                new Set(['sql_df'])
            )
            expect(errors[0]).toContain('output dataframe')
        })

        it('accepts a plain identifier', () => {
            expect(getNotebookVariableErrors([{ name: 'lookback_days', type: 'number', value: 30 }])).toEqual([null])
        })
    })

    describe('getNotebookVariableConflictNames', () => {
        it('collects the dataframe names of the revamped cells', () => {
            const content: JSONContent = {
                type: 'doc',
                content: [
                    { type: NotebookNodeType.SQLV2, attrs: { nodeId: 'a', returnVariable: 'sql_df', code: '' } },
                    { type: NotebookNodeType.PythonV2, attrs: { nodeId: 'b', returnVariable: 'frame', code: '' } },
                ],
            }
            expect(getNotebookVariableConflictNames(content)).toEqual(new Set(['sql_df', 'frame']))
        })
    })

    describe('getSavableNotebookVariables', () => {
        it('drops a declaration the API would reject', () => {
            // One bad name fails the whole PATCH, so it must not travel with the good ones.
            expect(
                getSavableNotebookVariables([
                    country,
                    { name: '', type: 'string', value: '' },
                    { name: 'look-back', type: 'number', value: 7 },
                ])
            ).toEqual([country])
        })

        it("keeps a declaration that clashes with a cell's output dataframe", () => {
            // The API stores this happily. Filtering it here would delete the person's variable
            // because some other cell was renamed to the same word.
            const clashing: NotebookVariable = { name: 'sql_df', type: 'string', value: 'US' }
            expect(getSavableNotebookVariables([clashing])).toEqual([clashing])
        })
    })

    describe('getRunnableNotebookVariables', () => {
        it('sends only the declarations that pass validation', () => {
            // An invalid name would reach the backend as a variable no cell can read, and a
            // duplicate would make which value binds depend on ordering.
            expect(
                getRunnableNotebookVariables([
                    country,
                    { name: 'look-back', type: 'number', value: 7 },
                    { ...country, value: 'DE' },
                ])
            ).toEqual([country])
        })
    })
})

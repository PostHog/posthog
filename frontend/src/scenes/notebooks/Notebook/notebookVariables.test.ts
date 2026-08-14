import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'
import {
    NOTEBOOK_VARIABLES_TAG,
    NotebookVariable,
    collectNotebookVariables,
    extractSqlVariableReferences,
    getNotebookVariableConflictNames,
    getNotebookVariableErrors,
    getRunnableNotebookVariables,
    parseNotebookVariableItems,
    serializeNotebookVariableItems,
} from './notebookVariables'

describe('notebookVariables', () => {
    const markdownContent = (markdown: string): JSONContent => ({
        type: 'doc',
        content: [{ type: NotebookNodeType.MarkdownNotebook, attrs: { nodeId: 'md', markdown } }],
    })

    const variablesMarkdown = (items: NotebookVariable[]): string =>
        `<${NOTEBOOK_VARIABLES_TAG} items={${JSON.stringify(items)}} />`

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

    describe('collectNotebookVariables', () => {
        it('reads declarations out of the markdown block', () => {
            const content = markdownContent(
                variablesMarkdown([
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'lookback_days', type: 'number', value: 30 },
                ])
            )
            expect(collectNotebookVariables(content)).toEqual([
                { name: 'country', type: 'string', value: 'US' },
                { name: 'lookback_days', type: 'number', value: 30 },
            ])
        })

        it('keeps the first of two declarations sharing a name', () => {
            // The editor flags the second as invalid, so what runs must be the one it marks valid.
            const content = markdownContent(
                variablesMarkdown([
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'country', type: 'string', value: 'DE' },
                ])
            )
            expect(collectNotebookVariables(content)).toEqual([{ name: 'country', type: 'string', value: 'US' }])
        })

        it('returns nothing for a notebook with no variables block', () => {
            expect(collectNotebookVariables(markdownContent('# Just prose'))).toEqual([])
        })
    })

    describe('markdown round trip', () => {
        it('survives a parse and re-serialize as a component block', () => {
            // Markdown is the only storage: a block that degrades to a paragraph on save loses
            // every value in it.
            const markdown = variablesMarkdown([{ name: 'country', type: 'string', value: 'US' }])
            const document = parseMarkdownNotebook(markdown)
            const block = document.nodes[0]

            expect(block.type).toBe('component')
            expect(block.type === 'component' && block.tagName).toBe(NOTEBOOK_VARIABLES_TAG)
            expect(block.type === 'component' ? parseNotebookVariableItems(block.props) : []).toEqual([
                { name: 'country', type: 'string', value: 'US' },
            ])
            expect(collectNotebookVariables(markdownContent(serializeMarkdownNotebook(document)))).toEqual([
                { name: 'country', type: 'string', value: 'US' },
            ])
        })

        it('drops a malformed entry without losing its neighbours', () => {
            const props = { items: ['nonsense', { name: 'country', type: 'string', value: 'US' }] }
            expect(parseNotebookVariableItems(props as never)).toEqual([
                { name: 'country', type: 'string', value: 'US' },
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
            const errors = getNotebookVariableErrors([
                { name: 'country', type: 'string', value: 'US' },
                { name: 'country', type: 'string', value: 'DE' },
            ])
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

    describe('getRunnableNotebookVariables', () => {
        it('sends only the declarations that pass validation', () => {
            // An invalid name would reach the backend as a variable no cell can read, and a
            // duplicate would make which value binds depend on ordering.
            expect(
                getRunnableNotebookVariables([
                    { name: 'country', type: 'string', value: 'US' },
                    { name: 'look-back', type: 'number', value: 7 },
                    { name: 'country', type: 'string', value: 'DE' },
                ])
            ).toEqual([{ name: 'country', type: 'string', value: 'US' }])
        })
    })

    describe('serializeNotebookVariableItems', () => {
        it('keeps only the persisted fields', () => {
            expect(serializeNotebookVariableItems([{ name: 'country', type: 'string', value: 'US' }])).toEqual([
                { name: 'country', type: 'string', value: 'US' },
            ])
        })
    })
})

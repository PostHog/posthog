import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from '../../Notebook/markdownNotebookV2'
import { NotebookNodeType } from '../../types'
import { inferGenUIInputs } from './genUIInputInference'

describe('inferGenUIInputs', () => {
    const frameNode = (nodeId: string, returnVariable: string): Record<string, unknown> => ({
        type: NotebookNodeType.SQLV2,
        attrs: { nodeId, returnVariable, code: 'select 1' },
    })
    const genUINode = (nodeId: string): Record<string, unknown> => ({
        type: NotebookNodeType.GenUI,
        attrs: { nodeId, prompt: '' },
    })

    it('uses available dataframe names mentioned in the prompt', () => {
        const content = {
            type: 'doc',
            content: [frameNode('locations', 'locations_df'), frameNode('sales', 'sales_df'), genUINode('chart')],
        }

        expect(inferGenUIInputs(content, 'chart', 'Plot sales_df on a globe', 'locations_df')).toEqual({
            names: ['sales_df'],
            serialized: 'sales_df',
        })
    })

    it('uses the four closest preceding dataframes when the prompt does not name one', () => {
        const content = {
            type: 'doc',
            content: [
                frameNode('a', 'a_df'),
                frameNode('b', 'b_df'),
                frameNode('c', 'c_df'),
                frameNode('d', 'd_df'),
                frameNode('e', 'e_df'),
                genUINode('chart'),
                frameNode('future', 'future_df'),
            ],
        }

        expect(inferGenUIInputs(content, 'chart', 'Build an interactive chart', '')).toEqual({
            names: ['b_df', 'c_df', 'd_df', 'e_df'],
            serialized: 'b_df, c_df, d_df, e_df',
        })
    })

    it('keeps configured inputs when the prompt does not name a dataframe', () => {
        const content = {
            type: 'doc',
            content: [frameNode('locations', 'locations_df'), frameNode('sales', 'sales_df'), genUINode('chart')],
        }

        expect(inferGenUIInputs(content, 'chart', 'Build an interactive globe', 'locations_df')).toEqual({
            names: ['locations_df'],
            serialized: 'locations_df',
        })
    })

    it('detects dataframe names inside a markdown notebook', () => {
        const markdown = [
            serializeMarkdownNotebookComponent('PythonV2', {
                nodeId: 'source',
                returnVariable: 'pandas_df',
                code: 'pandas_df = make_data()',
            }),
            serializeMarkdownNotebookComponent('GenUI', {
                nodeId: 'chart',
                prompt: 'Render pandas_df',
            }),
        ].join('\n\n')

        expect(inferGenUIInputs(buildMarkdownNotebookContent(markdown), 'chart', 'Render pandas_df', '')).toEqual({
            names: ['pandas_df'],
            serialized: 'pandas_df',
        })
    })
})

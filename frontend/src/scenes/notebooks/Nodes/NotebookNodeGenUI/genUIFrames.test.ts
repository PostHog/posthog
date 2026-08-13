import { serializeMarkdownNotebookComponent } from '../../Notebook/markdownNotebookV2'
import { buildMarkdownNotebookContent } from '../../Notebook/markdownNotebookV2'
import { buildGenUIFrames, getGenUIFrameSchemas, parseGenUIInputNames } from './genUIFrames'

describe('genUIFrames', () => {
    it('exposes only requested saved dataframe preview rows from markdown notebooks', () => {
        const markdown = [
            serializeMarkdownNotebookComponent('PythonV2', {
                nodeId: 'python-1',
                returnVariable: 'pandas_df',
                code: 'pandas_df',
                result: {
                    columns: ['lat', 'lng', 'timestamp'],
                    types: [
                        ['lat', 'float64'],
                        ['lng', 'float64'],
                        ['timestamp', 'datetime64[ns]'],
                    ],
                    row_count: 2,
                    first_page: [
                        [51.5, -0.1, '2026-01-01T00:00:00Z'],
                        [40.7, -74, '2026-01-02T00:00:00Z'],
                    ],
                },
            }),
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'sql-1',
                returnVariable: 'private_df',
                code: 'select 1',
                result: { columns: ['secret'], row_count: 1, first_page: [['hidden']] },
            }),
        ].join('\n\n')

        const frames = buildGenUIFrames(buildMarkdownNotebookContent(markdown), 'pandas_df')

        expect(frames).toEqual({
            pandas_df: {
                name: 'pandas_df',
                columns: [
                    { name: 'lat', type: 'float64' },
                    { name: 'lng', type: 'float64' },
                    { name: 'timestamp', type: 'datetime64[ns]' },
                ],
                rows: [
                    [51.5, -0.1, '2026-01-01T00:00:00Z'],
                    [40.7, -74, '2026-01-02T00:00:00Z'],
                ],
                totalRowCount: 2,
                includedRowCount: 2,
                truncated: false,
            },
        })
    })

    it('normalizes and deduplicates dataframe names', () => {
        expect(
            parseGenUIInputNames(
                `pandas_df, other_df pandas_df invalid-name third_df fourth_df fifth_df ${'x'.repeat(129)}`
            )
        ).toEqual(['pandas_df', 'other_df', 'third_df', 'fourth_df'])
    })

    it('keeps dataframe rows out of the generation schema', () => {
        const markdown = serializeMarkdownNotebookComponent('PythonV2', {
            nodeId: 'python-1',
            returnVariable: 'pandas_df',
            code: 'pandas_df',
            result: {
                types: [['value', 'string']],
                row_count: 1,
                first_page: [['private-row-value']],
            },
        })

        const { schemas } = getGenUIFrameSchemas(buildMarkdownNotebookContent(markdown), 'pandas_df')

        expect(schemas).toEqual([
            {
                name: 'pandas_df',
                columns: [{ name: 'value', type: 'string' }],
                totalRowCount: 1,
                includedRowCount: 1,
                truncated: false,
            },
        ])
        expect(JSON.stringify(schemas)).not.toContain('private-row-value')
    })

    it('enforces column, row, and cell limits', () => {
        const columns = Array.from({ length: 101 }, (_, index) => [`column_${index}`, 'string'])
        const rows = Array.from({ length: 105 }, () => Array.from({ length: 101 }, () => 'x'))
        rows[0][0] = 'x'.repeat(4097)
        const markdown = serializeMarkdownNotebookComponent('PythonV2', {
            nodeId: 'python-1',
            returnVariable: 'pandas_df',
            code: 'pandas_df',
            result: { types: columns, row_count: 105, first_page: rows },
        })

        const frame = buildGenUIFrames(buildMarkdownNotebookContent(markdown), 'pandas_df').pandas_df

        expect(frame.columns).toHaveLength(100)
        expect(frame.includedRowCount).toBe(100)
        expect(frame.rows[0]).toHaveLength(100)
        expect(String(frame.rows[0][0])).toHaveLength(4096)
        expect(frame.truncated).toBe(true)
    })

    it('enforces the serialized frame byte limit', () => {
        const markdown = serializeMarkdownNotebookComponent('PythonV2', {
            nodeId: 'python-1',
            returnVariable: 'pandas_df',
            code: 'pandas_df',
            result: {
                types: [['value', 'string']],
                row_count: 100,
                first_page: Array.from({ length: 100 }, () => ['x'.repeat(4096)]),
            },
        })

        const frame = buildGenUIFrames(buildMarkdownNotebookContent(markdown), 'pandas_df').pandas_df

        expect(frame.includedRowCount).toBeLessThan(100)
        expect(frame.truncated).toBe(true)
        expect(JSON.stringify(frame).length).toBeLessThanOrEqual(200 * 1024)
    })
})

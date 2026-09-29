import type { BrowserKernelClient } from './BrowserKernelClient'
import { recordableEnvelope, stageBrowserInputs } from './browserKernelRun'

describe('browserKernelRun', () => {
    it('fetches each upstream result once, and never one the kernel already holds', async () => {
        const client = {
            hasInput: jest.fn(async (key: string) => key === 'held-run'),
        } as unknown as BrowserKernelClient
        const fetchRows = jest.fn(async (key: string) => ({ key, columns: ['n'], types: [], values: [[1]] }))

        const { payloadInputs, staged } = await stageBrowserInputs(
            client,
            [
                { name: 'held', kind: 'hogql', node_id: 'a', key: 'held-run', query: 'select 1' },
                { name: 'fresh', kind: 'hogql', node_id: 'b', key: 'fresh-run', query: 'select 2' },
                { name: 'alias', kind: 'hogql', node_id: 'b', key: 'fresh-run', query: 'select 2' },
                { name: 'py_df', kind: 'local' },
            ],
            fetchRows
        )

        expect(fetchRows.mock.calls).toEqual([['fresh-run', 'select 2']])
        expect(staged.map((input) => input.key)).toEqual(['fresh-run'])
        expect(payloadInputs).toEqual([
            { name: 'held', kind: 'hogql', node_id: 'a', key: 'held-run' },
            { name: 'fresh', kind: 'hogql', node_id: 'b', key: 'fresh-run' },
            { name: 'alias', kind: 'hogql', node_id: 'b', key: 'fresh-run' },
            { name: 'py_df', kind: 'local' },
        ])
    })

    it.each([
        ['keeps figures that fit', 100, 1],
        ['drops figures past the size limit', 5_000_000, 0],
    ])('%s', (_name, figureSize, expectedFigures) => {
        const recorded = recordableEnvelope({
            status: 'ok',
            columns: ['n'],
            types: [['n', 'Int64']],
            row_count: 1,
            first_page: [[1]],
            has_more: false,
            stderr: '',
            media: [{ mime_type: 'image/png', data: 'x'.repeat(figureSize) }],
            result_id: 'kernel-only',
            frames: [],
        })

        expect(recorded.media).toHaveLength(expectedFigures)
        expect(recorded).not.toHaveProperty('frames')
        expect(recorded).not.toHaveProperty('result_id')
        expect(recorded.first_page).toEqual([[1]])
    })
})

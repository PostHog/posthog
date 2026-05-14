import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildCommandParams, getProjectIdOverride } from './cli-args.js'

describe('getProjectIdOverride', () => {
    const cases: Array<{ name: string; argv: Record<string, unknown>; expected: string | undefined }> = [
        { name: 'uses camel-cased yargs projectId values', argv: { projectId: '123' }, expected: '123' },
        { name: 'uses dashed yargs project-id values', argv: { 'project-id': '456' }, expected: '456' },
        { name: 'trims empty project IDs away', argv: { projectId: '   ' }, expected: undefined },
        { name: 'trims dashed empty project IDs away', argv: { 'project-id': '   ' }, expected: undefined },
        {
            name: 'prefers camel-cased values when both keys are set',
            argv: { projectId: '123', 'project-id': '456' },
            expected: '123',
        },
    ]

    for (const { name, argv, expected } of cases) {
        it(name, () => {
            assert.equal(getProjectIdOverride(argv), expected)
        })
    }
})

describe('buildCommandParams', () => {
    it('removes CLI-only options while preserving API parameters', () => {
        assert.deepEqual(
            buildCommandParams({
                _: ['feature-flags', 'list'],
                $0: 'ph',
                mcpContext: {},
                json: true,
                jq: '.[0]',
                projectId: '123',
                'project-id': '123',
                id: 'flag-id',
                search: 'checkout',
            }),
            { id: 'flag-id', search: 'checkout' }
        )
    })
})

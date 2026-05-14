import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildCommandParams, getProjectIdOverride } from './cli-args.js'

describe('getProjectIdOverride', () => {
    it('uses camel-cased yargs projectId values', () => {
        assert.equal(getProjectIdOverride({ projectId: '123' }), '123')
    })

    it('uses dashed yargs project-id values', () => {
        assert.equal(getProjectIdOverride({ 'project-id': '456' }), '456')
    })

    it('trims empty project IDs away', () => {
        assert.equal(getProjectIdOverride({ projectId: '   ' }), undefined)
    })
})

describe('buildCommandParams', () => {
    it('removes CLI-only options while preserving API parameters', () => {
        assert.deepEqual(
            buildCommandParams({
                _: ['feature-flags', 'list'],
                $0: 'ph',
                mcpContext: {},
                json: true,
                projectId: '123',
                'project-id': '123',
                id: 'flag-id',
                search: 'checkout',
            }),
            { id: 'flag-id', search: 'checkout' }
        )
    })
})

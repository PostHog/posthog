import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { applyJqFilter } from './output.js'

describe('applyJqFilter', () => {
    it('extracts a top-level property', async () => {
        const out = await applyJqFilter('.name', { name: 'flag-a', active: true })
        assert.equal(out.trim(), '"flag-a"')
    })

    it('selects fields from each item in an array', async () => {
        const out = await applyJqFilter(
            '[.results[] | {id, key}]',
            { results: [{ id: 1, key: 'a', name: 'first' }, { id: 2, key: 'b', name: 'second' }] }
        )
        assert.deepEqual(JSON.parse(out), [{ id: 1, key: 'a' }, { id: 2, key: 'b' }])
    })

    it('filters with a predicate', async () => {
        const out = await applyJqFilter(
            '[.results[] | select(.active)]',
            { results: [{ id: 1, active: true }, { id: 2, active: false }, { id: 3, active: true }] }
        )
        assert.deepEqual(JSON.parse(out), [{ id: 1, active: true }, { id: 3, active: true }])
    })

    it('rejects an invalid jq expression', async () => {
        await assert.rejects(() => applyJqFilter('.[', { foo: 'bar' }))
    })
})

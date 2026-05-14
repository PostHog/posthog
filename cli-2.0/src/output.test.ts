import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { applyJqFilter } from './output.js'

describe('applyJqFilter', () => {
    const cases: Array<{ name: string; filter: string; input: unknown; expected: unknown }> = [
        {
            name: 'extracts a top-level property',
            filter: '.name',
            input: { name: 'flag-a', active: true },
            expected: 'flag-a',
        },
        {
            name: 'selects fields from each item in an array',
            filter: '[.results[] | {id, key}]',
            input: {
                results: [
                    { id: 1, key: 'a', name: 'first' },
                    { id: 2, key: 'b', name: 'second' },
                ],
            },
            expected: [
                { id: 1, key: 'a' },
                { id: 2, key: 'b' },
            ],
        },
        {
            name: 'filters with a predicate',
            filter: '[.results[] | select(.active)]',
            input: {
                results: [
                    { id: 1, active: true },
                    { id: 2, active: false },
                    { id: 3, active: true },
                ],
            },
            expected: [
                { id: 1, active: true },
                { id: 3, active: true },
            ],
        },
    ]

    for (const { name, filter, input, expected } of cases) {
        it(name, async () => {
            const out = await applyJqFilter(filter, input)
            assert.deepEqual(JSON.parse(out), expected)
        })
    }

    it('rejects an invalid jq expression', async () => {
        await assert.rejects(() => applyJqFilter('.[', { foo: 'bar' }))
    })
})

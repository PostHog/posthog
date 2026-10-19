import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { openDepth } from './check-stack-depth.mjs'

const layers = (...states) => ({ pull_requests: states.map((state, i) => ({ number: i + 1, state })) })

describe('openDepth', () => {
    for (const { name, stack, prNumber, expected } of [
        {
            name: 'counts the top layer of a full stack',
            stack: layers('open', 'open', 'open', 'open', 'open', 'open'),
            prNumber: 6,
            expected: 6,
        },
        {
            name: 'skips merged layers below',
            stack: layers('closed', 'closed', 'closed', 'closed', 'open', 'open', 'open'),
            prNumber: 7,
            expected: 3,
        },
        {
            name: 'ignores layers above',
            stack: layers('open', 'open', 'open', 'open', 'open', 'open', 'open'),
            prNumber: 2,
            expected: 2,
        },
    ]) {
        it(name, () => {
            assert.equal(openDepth(stack, prNumber), expected)
        })
    }
})

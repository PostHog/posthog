import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { chainedOpenDepth } from './check-stack-depth.mjs'

const layers = (baseRef, firstNumber, ...states) => ({
    base: { ref: baseRef },
    pull_requests: states.map((state, i) => ({ number: firstNumber + i, state })),
})

const lowerStack = layers('master', 1, 'open', 'open', 'open', 'open')

const openPrsByHead = {
    'lower-top': { number: 4, stack: { number: 100 } },
    'plain-feature': { number: 20, stack: null, base: { ref: 'master' } },
}

describe('chainedOpenDepth', () => {
    for (const { name, stack, prNumber, expected } of [
        {
            name: 'counts the top layer of a full stack',
            stack: layers('master', 1, 'open', 'open', 'open', 'open', 'open', 'open'),
            prNumber: 6,
            expected: 6,
        },
        {
            name: 'skips merged layers below',
            stack: layers('master', 1, 'closed', 'closed', 'closed', 'closed', 'open', 'open', 'open'),
            prNumber: 7,
            expected: 3,
        },
        {
            name: 'ignores layers above',
            stack: layers('master', 1, 'open', 'open', 'open', 'open', 'open', 'open', 'open'),
            prNumber: 2,
            expected: 2,
        },
        {
            name: 'adds the open layers of the stack it starts from',
            stack: layers('lower-top', 11, 'open', 'open', 'open'),
            prNumber: 13,
            expected: 7,
        },
        {
            name: 'adds an unstacked open pull request it starts from',
            stack: layers('plain-feature', 11, 'open', 'open'),
            prNumber: 12,
            expected: 3,
        },
    ]) {
        it(name, async () => {
            const depth = await chainedOpenDepth({
                stack,
                prNumber,
                defaultBranch: 'master',
                findOpenPrByHead: async (ref) => openPrsByHead[ref],
                getStack: async () => lowerStack,
            })
            assert.equal(depth, expected)
        })
    }
})

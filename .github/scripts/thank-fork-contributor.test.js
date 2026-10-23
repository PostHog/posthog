// Run with: node --test .github/scripts/thank-fork-contributor.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { MARKER, parseContribution, skipReason, buildComment } = require('./thank-fork-contributor')

const forkPr = (overrides = {}) => ({
    isCrossRepository: true,
    author: { login: 'Indira-kumar' },
    comments: { nodes: [] },
    ...overrides,
})

test.describe('thank-fork-contributor', () => {
    for (const [body, expected] of [
        [
            '- Contributed by @Indira-kumar in #106575, which cannot merge because backend CI does not run for fork PRs.',
            { login: 'Indira-kumar', forkPrNumber: 106575 },
        ],
        ['Fixes the bug reported in #106575.', null],
        [null, null],
    ]) {
        test(`parseContribution(${JSON.stringify(body)})`, () => {
            assert.deepEqual(parseContribution(body), expected)
        })
    }

    for (const [name, pr, expected] of [
        ['fork PR by the contributor', forkPr(), null],
        ['login differs only in case', forkPr({ author: { login: 'indira-kumar' } }), null],
        ['missing PR', null, 'pull request not found'],
        ['same-repo PR', forkPr({ isCrossRepository: false }), 'not opened from a fork'],
        ['fork PR by someone else', forkPr({ author: { login: 'someone' } }), 'opened by someone, not Indira-kumar'],
        [
            'contributor already told',
            forkPr({ comments: { nodes: [{ body: `${MARKER}\nThanks` }] } }),
            'contributor already told',
        ],
    ]) {
        test(`skipReason: ${name}`, () => {
            assert.equal(skipReason(pr, 'Indira-kumar'), expected)
        })
    }

    test('buildComment claims co-author credit only when GitHub gives it', () => {
        const args = { login: 'Indira-kumar', mergedPrNumber: 122491, mergeCommitSha: '1a3a80f9' }
        assert.match(buildComment({ ...args, credited: true }), /co-author/)
        assert.doesNotMatch(buildComment({ ...args, credited: false }), /co-author/)
    })
})

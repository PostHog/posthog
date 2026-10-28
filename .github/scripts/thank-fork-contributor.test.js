// Run with: node --test .github/scripts/thank-fork-contributor.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const thankForkContributor = require('./thank-fork-contributor')
const { THANKS_MARKER, parseContribution, skipReason, buildComment } = thankForkContributor

const forkPr = (overrides = {}) => ({
    state: 'OPEN',
    isCrossRepository: true,
    author: { login: 'Jane-Doe' },
    comments: { nodes: [] },
    ...overrides,
})

const MERGED_PR = {
    body: '<!-- fork-pr: 1001 @Jane-Doe -->',
    mergeCommit: { authors: { nodes: [{ user: { login: 'Jane-Doe' } }] } },
}

function fakeGithub(forkPrResult) {
    const calls = []
    return {
        calls,
        graphql: async (query, { number }) => {
            if (number === 1001) {
                if (forkPrResult instanceof Error) {
                    throw forkPrResult
                }
                return { repository: { pullRequest: forkPrResult } }
            }
            return { repository: { pullRequest: MERGED_PR } }
        },
        rest: {
            issues: { createComment: async (args) => calls.push(['comment', args.issue_number]) },
            pulls: { update: async (args) => calls.push(['close', args.pull_number]) },
        },
    }
}

const context = { repo: { owner: 'PostHog', repo: 'posthog' }, payload: { pull_request: { number: 1002 } } }
const core = { info: () => {}, warning: () => {} }

test.describe('thank-fork-contributor', () => {
    for (const [body, expected] of [
        [
            '## Problem\n\n<!-- fork-pr: 1001 @Jane-Doe -->\n- Contributed by @Jane-Doe in #1001.',
            { forkPrNumber: 1001, login: 'Jane-Doe' },
        ],
        ['- Contributed by @Jane-Doe in #1001, which cannot merge.', null],
        [null, null],
    ]) {
        test(`parseContribution(${JSON.stringify(body)})`, () => {
            assert.deepEqual(parseContribution(body), expected)
        })
    }

    for (const [name, pr, expected] of [
        ['fork PR by the contributor', forkPr(), null],
        ['login differs only in case', forkPr({ author: { login: 'jane-doe' } }), null],
        ['missing PR', null, 'pull request not found'],
        ['same-repo PR', forkPr({ isCrossRepository: false }), 'not opened from a fork'],
        ['fork PR by someone else', forkPr({ author: { login: 'someone' } }), 'opened by someone, not Jane-Doe'],
    ]) {
        test(`skipReason: ${name}`, () => {
            assert.equal(skipReason(pr, 'Jane-Doe'), expected)
        })
    }

    test('buildComment claims co-author credit only when GitHub gives it', () => {
        const args = { login: 'Jane-Doe', mergedPrNumber: 1002 }
        assert.match(buildComment({ ...args, credited: true }), /co-author/)
        assert.doesNotMatch(buildComment({ ...args, credited: false }), /co-author/)
    })

    const notFound = Object.assign(new Error('not found'), { errors: [{ type: 'NOT_FOUND' }] })
    for (const [name, forkPrResult, expectedCalls] of [
        [
            'open fork PR gets a comment and is closed',
            forkPr(),
            [
                ['comment', 1001],
                ['close', 1001],
            ],
        ],
        [
            'a rerun after a failed close only closes',
            forkPr({ comments: { nodes: [{ body: THANKS_MARKER }] } }),
            [['close', 1001]],
        ],
        ['a closed fork PR only gets the comment', forkPr({ state: 'CLOSED' }), [['comment', 1001]]],
        ['a PR number that does not exist is skipped', notFound, []],
    ]) {
        test(name, async () => {
            const github = fakeGithub(forkPrResult)
            await thankForkContributor({ github, context, core })
            assert.deepEqual(github.calls, expectedCalls)
        })
    }
})

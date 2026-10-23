// Run with: node --test .github/scripts/thank-fork-contributor.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const thankForkContributor = require('./thank-fork-contributor')
const { MARKER, parseContribution, skipReason, buildComment } = thankForkContributor

const forkPr = (overrides = {}) => ({
    state: 'OPEN',
    isCrossRepository: true,
    author: { login: 'Indira-kumar' },
    comments: { nodes: [] },
    ...overrides,
})

const MERGED_PR = {
    body: 'Contributed by @Indira-kumar in #106575, which cannot merge.',
    mergeCommit: { authors: { nodes: [{ user: { login: 'Indira-kumar' } }] } },
}

function fakeGithub(forkPrResult) {
    const calls = []
    return {
        calls,
        graphql: async (query, { number }) => {
            if (number === 106575) {
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

const context = { repo: { owner: 'PostHog', repo: 'posthog' }, payload: { pull_request: { number: 122491 } } }
const core = { info: () => {}, warning: () => {} }

test.describe('thank-fork-contributor', () => {
    for (const [body, expected] of [
        [
            '- Contributed by @Indira-kumar in #106575, which cannot merge because backend CI does not run for fork PRs.',
            { login: 'Indira-kumar', forkPrNumber: 106575 },
        ],
        [
            'Contributed by @Indira-kumar in [select slack workspace](https://github.com/PostHog/posthog/pull/106575), which cannot merge.',
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
    ]) {
        test(`skipReason: ${name}`, () => {
            assert.equal(skipReason(pr, 'Indira-kumar'), expected)
        })
    }

    test('buildComment claims co-author credit only when GitHub gives it', () => {
        const args = { login: 'Indira-kumar', mergedPrNumber: 122491 }
        assert.match(buildComment({ ...args, credited: true }), /co-author/)
        assert.doesNotMatch(buildComment({ ...args, credited: false }), /co-author/)
    })

    const notFound = Object.assign(new Error('not found'), { errors: [{ type: 'NOT_FOUND' }] })
    for (const [name, forkPrResult, expectedCalls] of [
        [
            'open fork PR gets a comment and is closed',
            forkPr(),
            [
                ['comment', 106575],
                ['close', 106575],
            ],
        ],
        [
            'a rerun after a failed close only closes',
            forkPr({ comments: { nodes: [{ body: MARKER }] } }),
            [['close', 106575]],
        ],
        ['a closed fork PR only gets the comment', forkPr({ state: 'CLOSED' }), [['comment', 106575]]],
        ['a PR number that does not exist is skipped', notFound, []],
    ]) {
        test(name, async () => {
            const github = fakeGithub(forkPrResult)
            await thankForkContributor({ github, context, core })
            assert.deepEqual(github.calls, expectedCalls)
        })
    }
})

// Run with: node --test .github/scripts/require-owner-review.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { teamsForFiles, evaluate, latestApprovers } = require('./require-owner-review')

const CONFIG_TEXT = `
# a comment
products/cdp/** @PostHog/team-workflows
nodejs/src/cdp/** @PostHog/team-workflows
products/cdp/backend/vendor/** 
posthog/hogql/** @PostHog/hogql
`

const MEMBERS = new Map([
    ['team-workflows', new Set(['dmarchuk', 'mayteio'])],
    ['hogql', new Set(['someone'])],
])

for (const [name, filenames, expected] of [
    ['a gated backend file', ['products/cdp/backend/api/hog_function.py'], ['team-workflows']],
    ['a gated worker file', ['nodejs/src/cdp/managed-alert-events.ts'], ['team-workflows']],
    ['two teams at once', ['products/cdp/x.py', 'posthog/hogql/printer.py'], ['hogql', 'team-workflows']],
    ['an unlisted path', ['products/alerts/backend/api.py'], []],
    ['a generated client only', ['products/cdp/frontend/generated/api.schemas.ts'], []],
    ['a lockfile only', ['pnpm-lock.yaml'], []],
    ['an owner-less reset line', ['products/cdp/backend/vendor/lib.py'], []],
    ['a gated file beside an excluded one', ['pnpm-lock.yaml', 'products/cdp/x.py'], ['team-workflows']],
]) {
    test(`teamsForFiles: ${name}`, () => {
        assert.deepEqual(teamsForFiles(CONFIG_TEXT, filenames), expected)
    })
}

for (const [name, input, expectedState] of [
    // The case a CODEOWNERS entry gets wrong: the owning team wrote it, so a bot
    // approval is enough and the team does not gate itself.
    ['author on the team, approved by a bot', { authorLogin: 'mayteio', approvers: ['stamphog[bot]'] }, 'success'],
    ['another team, approved by an owner', { authorLogin: 'willwearing', approvers: ['dmarchuk'] }, 'success'],
    ['another team, approved by a third party', { authorLogin: 'willwearing', approvers: ['pawel-cebula'] }, 'failure'],
    ['another team, no approval at all', { authorLogin: 'willwearing', approvers: [] }, 'failure'],
    ['a bot author needs a human owner', { authorLogin: 'posthog[bot]', approvers: ['stamphog[bot]'] }, 'failure'],
]) {
    test(`evaluate: ${name}`, () => {
        const result = evaluate({
            teams: ['team-workflows'],
            authorLogin: input.authorLogin,
            approvers: new Set(input.approvers),
            membersByTeam: MEMBERS,
        })
        assert.equal(result.state, expectedState)
    })
}

test('evaluate: every gating team has to be satisfied on its own', () => {
    const result = evaluate({
        teams: ['team-workflows', 'hogql'],
        authorLogin: 'dmarchuk',
        approvers: new Set([]),
        membersByTeam: MEMBERS,
    })
    assert.equal(result.state, 'failure')
    assert.deepEqual(result.missing, ['hogql'])
})

test('evaluate: a diff with no gated path passes', () => {
    const result = evaluate({
        teams: [],
        authorLogin: 'anyone',
        approvers: new Set([]),
        membersByTeam: MEMBERS,
    })
    assert.equal(result.state, 'success')
})

test('latestApprovers: a dismissed approval stops counting', () => {
    const approvers = latestApprovers([
        { user: { login: 'dmarchuk' }, state: 'APPROVED' },
        { user: { login: 'dmarchuk' }, state: 'DISMISSED' },
        { user: { login: 'mayteio' }, state: 'COMMENTED' },
        { user: { login: 'mayteio' }, state: 'APPROVED' },
    ])
    assert.deepEqual([...approvers], ['mayteio'])
})

test('latestApprovers: changes requested after an approval stops counting', () => {
    const approvers = latestApprovers([
        { user: { login: 'dmarchuk' }, state: 'APPROVED' },
        { user: { login: 'dmarchuk' }, state: 'CHANGES_REQUESTED' },
    ])
    assert.deepEqual([...approvers], [])
})

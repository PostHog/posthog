const test = require('node:test')
const assert = require('node:assert/strict')
const { decidePreview } = require('./desktop-preview-decision')

const skip = { build: false, desktop: false, installers: false, teardown: false, retireDesktop: false }
const build = { ...skip, build: true }
const desktop = { ...build, desktop: true, installers: true }
const teardown = { ...skip, teardown: true }
const cases = [
    ['ordinary PR', {}, skip],
    ['desktop-only draft push', { labels: ['desktop-preview'] }, desktop],
    ['backend-only push keeps the installers', { labels: ['desktop-preview'], desktopChanged: false }, { ...desktop, installers: false }],
    ['desktop label added without desktop changes', { action: 'labeled', label: 'desktop-preview', labels: ['desktop-preview'], desktopChanged: false }, { ...desktop, installers: false }],
    ['desktop label added', { action: 'labeled', label: 'desktop-preview', labels: ['desktop-preview'] }, desktop],
    ['hogbox opt-in', { labels: ['hogbox-preview'] }, build],
    ['frontend auto-preview', { autoPreviewEligible: true }, build],
    ['both preview labels', { labels: ['desktop-preview', 'hogbox-preview'] }, desktop],
    ['both installer labels', { labels: ['desktop-preview', 'desktop-build-installer'] }, desktop],
    ['unrelated label added', { action: 'labeled', label: 'bug', labels: ['desktop-preview', 'bug'] }, skip],
    ['unrelated label removed', { action: 'unlabeled', label: 'bug', labels: ['desktop-preview'] }, skip],
    ['no-preview suppresses pushes', { labels: ['desktop-preview', 'no-preview'] }, skip],
    ['no-preview suppresses dispatch', { event: 'workflow_dispatch', labels: ['desktop-preview', 'no-preview'] }, skip],
    ['no-preview added', { action: 'labeled', label: 'no-preview', labels: ['desktop-preview', 'no-preview'] }, { ...teardown, retireDesktop: true }],
    ['no-preview removed', { action: 'unlabeled', label: 'no-preview', labels: ['desktop-preview'] }, desktop],
    ['desktop removed, no demand', { action: 'unlabeled', label: 'desktop-preview' }, { ...teardown, retireDesktop: true }],
    ['desktop removed, hogbox retained', { action: 'unlabeled', label: 'desktop-preview', labels: ['hogbox-preview'] }, { ...skip, retireDesktop: true }],
    ['desktop removed, auto-preview retained', { action: 'unlabeled', label: 'desktop-preview', autoPreviewEligible: true }, { ...skip, retireDesktop: true }],
    ['hogbox removed, desktop retained', { action: 'unlabeled', label: 'hogbox-preview', labels: ['desktop-preview'] }, skip],
    ['hogbox removed, no demand', { action: 'unlabeled', label: 'hogbox-preview' }, teardown],
    ['hogbox removed, auto-preview retained', { action: 'unlabeled', label: 'hogbox-preview', autoPreviewEligible: true }, skip],
    ['ready labeled draft', { action: 'ready_for_review', labels: ['desktop-preview'] }, skip],
    ['dispatch ordinary build', { event: 'workflow_dispatch' }, build],
    ['dispatch desktop build', { event: 'workflow_dispatch', labels: ['desktop-preview'] }, desktop],
]
for (const [name, input, expected] of cases) {
    test(name, () => assert.deepEqual(decidePreview({
        event: 'pull_request', action: 'synchronize', labels: [], repository: 'PostHog/posthog',
        pr: { draft: true, state: 'open', head: { repo: { full_name: 'PostHog/posthog' } }, user: { login: 'tester', type: 'User' } },
        ...input,
    }), expected))
}
for (const event of ['pull_request', 'workflow_dispatch']) {
    test(`${event} refuses forks and closed PRs`, () => {
        for (const pr of [
            { head: { repo: { full_name: 'someone/fork' } }, state: 'open' },
            { head: { repo: { full_name: 'PostHog/posthog' } }, state: 'closed' },
        ]) {
            assert.deepEqual(decidePreview({ event, pr, repository: 'PostHog/posthog', labels: ['desktop-preview'] }), skip)
        }
    })
}
test('bot previews require explicit dispatch', () => {
    const input = { pr: { head: { repo: { full_name: 'PostHog/posthog' } }, user: { type: 'Bot' } }, repository: 'PostHog/posthog', labels: ['desktop-preview'] }
    assert.deepEqual(decidePreview({ ...input, event: 'pull_request' }), skip)
    assert.deepEqual(decidePreview({ ...input, event: 'workflow_dispatch' }), desktop)
})
test('a dispatched bot preview still tears down', () => {
    // A bot preview exists only because a person dispatched it. Later label
    // events arrive as pull_request actions, and the cleanup branches must run
    // before the bot guard or the box + sticky comment leak until PR close.
    const botPr = { head: { repo: { full_name: 'PostHog/posthog' } }, user: { type: 'Bot' } }
    const base = { pr: botPr, repository: 'PostHog/posthog' }
    // no-preview added while a dispatched bot preview is live
    assert.deepEqual(decidePreview({ ...base, event: 'pull_request', action: 'labeled', label: 'no-preview', labels: ['desktop-preview', 'no-preview'] }), { ...teardown, retireDesktop: true })
    // desktop-preview removed from a bot PR with no other demand
    assert.deepEqual(decidePreview({ ...base, event: 'pull_request', action: 'unlabeled', label: 'desktop-preview', labels: [] }), { ...teardown, retireDesktop: true })
    // auto-eligibility cannot keep a bot preview alive on label removal
    assert.deepEqual(decidePreview({ ...base, event: 'pull_request', action: 'unlabeled', label: 'desktop-preview', labels: [], autoPreviewEligible: true }), { ...teardown, retireDesktop: true })
})

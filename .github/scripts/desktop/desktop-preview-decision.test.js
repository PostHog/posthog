const test = require('node:test')
const assert = require('node:assert/strict')
const { decidePreview } = require('./desktop-preview-decision')

const skip = { build: false, desktop: false, teardown: false, retireDesktop: false }
const build = { ...skip, build: true }
const desktop = { ...build, desktop: true }
const teardown = { ...skip, teardown: true }
const cases = [
    ['ordinary PR', {}, skip],
    ['desktop-only draft push', { labels: ['desktop-preview'] }, desktop],
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

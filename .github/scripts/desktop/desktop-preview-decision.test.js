// Run with: node --test .github/scripts/desktop/desktop-preview-decision.test.js
//
// Table-driven coverage of the label semantics in section 12 of the desktop
// preview plan. Every row is a workflow-visible outcome; the workflow's decide
// job is a thin adapter over this module.

const test = require('node:test')
const assert = require('node:assert/strict')

const { decideDesktopPreview, DESKTOP_LABEL, HOGBOX_LABEL, NO_PREVIEW_LABEL } =
    require('./desktop-preview-decision')

const REPO = 'PostHog/posthog'
const PR = (overrides = {}) => ({
    number: 123,
    draft: true,
    user: { login: 'a-person', type: 'User' },
    head: { repo: { full_name: REPO } },
    ...overrides,
})

const base = (overrides = {}) => ({
    event: 'pull_request',
    action: 'synchronize',
    pr: PR(),
    repository: REPO,
    labels: [],
    ...overrides,
})

test('adding desktop-preview to an eligible open PR provisions desktop + backend', () => {
    const out = decideDesktopPreview(
        base({ action: 'labeled', label: DESKTOP_LABEL, labels: [DESKTOP_LABEL] }),
    )
    assert.equal(out.action, 'build')
    assert.equal(out.desktop, true)
    assert.equal(out.backend, true)
})

test('a draft PR with the label gets the same opt-in as a ready PR', () => {
    const out = decideDesktopPreview(
        base({ action: 'labeled', label: DESKTOP_LABEL, labels: [DESKTOP_LABEL], pr: PR({ draft: true }) }),
    )
    assert.equal(out.action, 'build')
})

test('a push to a labeled PR reconciles the latest SHA', () => {
    const out = decideDesktopPreview(
        base({ action: 'synchronize', labels: [DESKTOP_LABEL] }),
    )
    assert.equal(out.action, 'build')
})

test('an unrelated label change does no expensive work', () => {
    const out = decideDesktopPreview(
        base({ action: 'labeled', label: 'team/desktop', labels: [DESKTOP_LABEL] }),
    )
    assert.equal(out.action, 'none')
})

test('no-preview suppresses the desktop preview while present', () => {
    const out = decideDesktopPreview(
        base({ labels: [DESKTOP_LABEL, NO_PREVIEW_LABEL] }),
    )
    assert.equal(out.action, 'none')
    assert.match(out.reason, /suppress/)
})

test('removing no-preview resumes reconciliation', () => {
    const out = decideDesktopPreview(
        base({
            action: 'unlabeled',
            label: NO_PREVIEW_LABEL,
            labels: [DESKTOP_LABEL],
        }),
    )
    assert.equal(out.action, 'build')
})

test('removing desktop-preview retires desktop artifacts but keeps a hogbox backend', () => {
    const out = decideDesktopPreview(
        base({
            action: 'unlabeled',
            label: DESKTOP_LABEL,
            labels: [HOGBOX_LABEL],
        }),
    )
    assert.equal(out.action, 'teardown')
    assert.equal(out.desktop, false)
    assert.equal(out.backend, true)
})

test('removing desktop-preview with no other demand retires the backend too', () => {
    const out = decideDesktopPreview(
        base({ action: 'unlabeled', label: DESKTOP_LABEL, labels: [] }),
    )
    assert.equal(out.action, 'teardown')
    assert.equal(out.backend, false)
})

test('both installer labels produce one coordinated decision, not two', () => {
    // desktop-build-installer stays on the ordinary workflow; only the
    // desktop-preview label reaches this module. With both present the
    // decision is identical to desktop-preview alone.
    const out = decideDesktopPreview(
        base({ labels: [DESKTOP_LABEL, 'desktop-build-installer'] }),
    )
    assert.equal(out.action, 'build')
    assert.equal(out.desktop, true)
})

test('a fork PR never gets provisioning or signing', () => {
    const out = decideDesktopPreview(
        base({
            labels: [DESKTOP_LABEL],
            pr: PR({ head: { repo: { full_name: 'someone-else/fork' } } }),
        }),
    )
    assert.equal(out.action, 'none')
})

test('a bot-authored PR never gets provisioning', () => {
    const out = decideDesktopPreview(
        base({
            labels: [DESKTOP_LABEL],
            pr: PR({ user: { login: 'dependabot[bot]', type: 'Bot' } }),
        }),
    )
    assert.equal(out.action, 'none')
})

test('workflow_dispatch reconciles current intent', () => {
    const out = decideDesktopPreview(base({ event: 'workflow_dispatch', labels: [DESKTOP_LABEL] }))
    assert.equal(out.action, 'build')
})

test('an ordinary PR with no desktop label does nothing here', () => {
    const out = decideDesktopPreview(base({ labels: [HOGBOX_LABEL] }))
    assert.equal(out.action, 'none')
    assert.equal(out.desktop, false)
    assert.equal(out.backend, true)
})

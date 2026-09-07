const test = require('node:test')
const assert = require('node:assert/strict')
const { composeDesktopPreviewComment, readRecord } = require('./desktop-preview-comment')

const base = {
    prNumber: 123,
    sha: 'a'.repeat(40),
    headSha: 'a'.repeat(40),
    url: 'https://preview.example.com',
    backendReady: true,
    gateway: true,
    installersRequested: true,
    results: { macos: 'success', windows: 'success', linux: 'success' },
    runId: 200,
    runUrl: 'https://github.com/PostHog/posthog/actions/runs/200',
}
const skipped = { macos: 'skipped', windows: 'skipped', linux: 'skipped' }
const compose = (overrides) => composeDesktopPreviewComment({ ...base, ...overrides })
const storedInstallers = (body) => readRecord(body, 'installers')
const storedBackend = (body) => readRecord(body, 'backend')

test('a backend-only push keeps the installers testers already have', () => {
    const built = compose({}).body
    const backendOnly = compose({
        sha: 'b'.repeat(40),
        headSha: 'b'.repeat(40),
        installersRequested: false,
        results: skipped,
        runId: 300,
        existingBody: built,
    })
    assert.equal(storedInstallers(backendOnly.body).runId, 200)
    assert.equal(storedBackend(backendOnly.body).sha, 'b'.repeat(40))
    assert.match(backendOnly.body, /Download installers from run 200/)
})

test('installers built before a backend-only push still reach the comment', () => {
    // The installer run started on sha a and is still building when a
    // backend-only push moves the head to sha b. The newer run reports first,
    // so when the installer run reports, its own SHA is no longer the head.
    const backendFirst = compose({
        sha: 'b'.repeat(40),
        headSha: 'b'.repeat(40),
        installersRequested: false,
        results: skipped,
        runId: 300,
    }).body
    assert.match(backendFirst, /no installers yet/)

    const late = compose({ headSha: 'b'.repeat(40), existingBody: backendFirst })
    assert.equal(late.skip, undefined)
    assert.equal(storedInstallers(late.body).sha, 'a'.repeat(40))
    // The stale run must not drag the backend line back to its own SHA.
    assert.equal(storedBackend(late.body).sha, 'b'.repeat(40))
})

test('a superseded run with no installers writes nothing', () => {
    const result = compose({
        headSha: 'b'.repeat(40),
        installersRequested: false,
        results: skipped,
    })
    assert.equal(result.skip, true)
})

test('a late report cannot replace a newer installer build', () => {
    const newer = compose({ runId: 400, runUrl: 'https://github.com/PostHog/posthog/actions/runs/400' }).body
    const late = compose({
        runId: 100,
        runUrl: 'https://github.com/PostHog/posthog/actions/runs/100',
        headSha: 'b'.repeat(40),
        existingBody: newer,
    })
    assert.equal(storedInstallers(late.body).runId, 400)
})

test('a failed bring-up reports the failure without dropping the links', () => {
    const built = compose({}).body
    const failed = compose({
        sha: 'b'.repeat(40),
        headSha: 'b'.repeat(40),
        backendReady: false,
        gateway: false,
        results: skipped,
        runId: 300,
        existingBody: built,
    })
    assert.match(failed.body, /backend failed/)
    assert.equal(storedInstallers(failed.body).runId, 200)
})

test('a partial build is named per platform', () => {
    const body = compose({ results: { macos: 'success', windows: 'failure', linux: 'success' } }).body
    assert.match(body, /partially built/)
    assert.match(body, /\| Windows x64 \| ❌ failure \|/)
})

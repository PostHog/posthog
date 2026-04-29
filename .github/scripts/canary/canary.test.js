'use strict'

// Run with: `node --test .github/scripts/canary/canary.test.js`
// (uses Node's built-in test runner, no dependencies needed)

const test = require('node:test')
const assert = require('node:assert/strict')

const comment = require('./comment')
const state = require('./state')

const SAMPLE_STATE_YAML = `state:
  argocd-ui-extensions-api:
    image:
      dev: sha256:abc
  feature-flags:
    canary:
      enabled: true
      image: sha-1234567
      pr_number: 56789
      started_at: "2026-04-29T12:00:00Z"
      started_by: matheus-vb
      target_environment: prod-us
      weight: 5
    deploy_info:
      commit:
        author: someone
        sha: deadbeef
  posthog:
    image:
      dev: sha256:def
`

const SAMPLE_STATE_YAML_DISABLED = `state:
  feature-flags:
    canary:
      enabled: false
      image: null
      pr_number: null
      started_at: null
      started_by: null
      target_environment: null
      weight: 0
`

test('parseScalar handles common YAML scalars', () => {
    assert.equal(state.parseScalar('null'), null)
    assert.equal(state.parseScalar(''), null)
    assert.equal(state.parseScalar('~'), null)
    assert.equal(state.parseScalar('true'), true)
    assert.equal(state.parseScalar('false'), false)
    assert.equal(state.parseScalar('5'), 5)
    assert.equal(state.parseScalar('-3'), -3)
    assert.equal(state.parseScalar('"sha-abc"'), 'sha-abc')
    assert.equal(state.parseScalar("'quoted'"), 'quoted')
    assert.equal(state.parseScalar('plain-value'), 'plain-value')
})

test('parseCanaryBlock extracts the active canary block', () => {
    const result = state.parseCanaryBlock(SAMPLE_STATE_YAML)
    assert.deepEqual(result, {
        enabled: true,
        image: 'sha-1234567',
        pr_number: 56789,
        started_at: '2026-04-29T12:00:00Z',
        started_by: 'matheus-vb',
        target_environment: 'prod-us',
        weight: 5,
    })
})

test('parseCanaryBlock extracts a disabled canary block', () => {
    const result = state.parseCanaryBlock(SAMPLE_STATE_YAML_DISABLED)
    assert.deepEqual(result, {
        enabled: false,
        image: null,
        pr_number: null,
        started_at: null,
        started_by: null,
        target_environment: null,
        weight: 0,
    })
})

test('parseCanaryBlock returns null when feature-flags is missing', () => {
    assert.equal(state.parseCanaryBlock('state:\n  posthog:\n    image:\n      dev: x\n'), null)
    assert.equal(state.parseCanaryBlock(''), null)
    assert.equal(state.parseCanaryBlock(null), null)
})

test('derivePhase maps states to phases per the decision table', () => {
    const owned = { enabled: true, pr_number: 100, weight: 0 }
    const ownedRouting = { enabled: true, pr_number: 100, weight: 5 }
    const otherPr = { enabled: true, pr_number: 999, weight: 5 }
    const disabled = { enabled: false, pr_number: null, weight: 0 }

    assert.equal(state.derivePhase(disabled, null, 100), 'EXPIRED')
    assert.equal(state.derivePhase(otherPr, null, 100), 'EXPIRED')
    assert.equal(state.derivePhase(owned, { status: 'in_progress' }, 100), 'ROLLING_OUT')
    assert.equal(state.derivePhase(owned, { status: 'queued' }, 100), 'ROLLING_OUT')
    assert.equal(state.derivePhase(ownedRouting, { status: 'in_progress' }, 100), 'ROUTING')
    assert.equal(state.derivePhase(ownedRouting, { status: 'completed', conclusion: 'success' }, 100), 'HEALTHY')
    assert.equal(state.derivePhase(ownedRouting, { status: 'completed', conclusion: 'failure' }, 100), 'FAILED')
    assert.equal(state.derivePhase(owned, { status: 'completed', conclusion: 'cancelled' }, 100), 'CANCELED')
    // null run when canary is enabled and owned: still rolling out
    assert.equal(state.derivePhase(owned, null, 100), 'ROLLING_OUT')
})

test('parseMarker round-trips with renderMarker', () => {
    const meta = { phase: 'ROLLING_OUT', pr: '123', image: 'sha-abc1234', env: 'prod-us', charts_run_id: '456' }
    const rendered = comment.renderMarker(meta)
    assert.match(rendered, /<!-- pr-canary-status /)
    const body = `${rendered}\n\nrest of comment`
    const parsed = comment.parseMarker(body)
    assert.deepEqual(parsed, meta)
})

test('parseMarker is null for bodies without the marker', () => {
    assert.equal(comment.parseMarker('just a comment'), null)
    assert.equal(comment.parseMarker(''), null)
    assert.equal(comment.parseMarker(null), null)
})

test('isTerminalPhase classifies phases correctly', () => {
    assert.equal(comment.isTerminalPhase('HEALTHY'), true)
    assert.equal(comment.isTerminalPhase('FAILED'), true)
    assert.equal(comment.isTerminalPhase('CANCELED'), true)
    assert.equal(comment.isTerminalPhase('CONFLICT'), true)
    assert.equal(comment.isTerminalPhase('EXPIRED'), true)
    assert.equal(comment.isTerminalPhase('ROLLING_OUT'), false)
    assert.equal(comment.isTerminalPhase('BUILDING'), false)
    assert.equal(comment.isTerminalPhase('CANCELING'), false)
})

test('renderBody for ROLLING_OUT includes the marker, header, image, env, and run links', () => {
    const body = comment.renderBody({
        phase: 'ROLLING_OUT',
        fields: {
            pr: 123,
            image: 'sha-abc1234',
            env: 'prod-us',
            weight: 0,
            started_by: 'matheus-vb',
            started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
            dispatch_run_url: 'https://github.com/PostHog/posthog/actions/runs/999',
            charts_run_url: 'https://github.com/PostHog/charts/actions/runs/123',
        },
    })
    assert.match(body, /<!-- pr-canary-status phase=ROLLING_OUT/)
    assert.match(body, /Rolling out/)
    assert.match(body, /sha-abc1234/)
    assert.match(body, /prod-us/)
    assert.match(body, /posthog run/)
    assert.match(body, /charts run/)
    assert.match(body, /\/pr-canary cancel/)
    assert.match(body, /Auto-disables/)
})

test('renderBody for CONFLICT names the holder PR and points to cancel', () => {
    const body = comment.renderBody({
        phase: 'CONFLICT',
        fields: {
            pr: 200,
            holder_pr: 199,
            holder_actor: 'bob',
            env: 'prod-eu',
            weight: 5,
            started_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
        },
    })
    assert.match(body, /Canary already active for #199/)
    assert.match(body, /\/pr-canary cancel/)
    assert.match(body, /#199/)
    assert.match(body, /48 hours/)
})

test('renderBody for HEALTHY shows expiry and cancel hint', () => {
    const body = comment.renderBody({
        phase: 'HEALTHY',
        fields: {
            pr: 123,
            image: 'sha-deadbee',
            env: 'dev',
            weight: 5,
            started_by: 'matheus-vb',
            started_at: new Date().toISOString(),
            dispatch_run_url: 'https://github.com/PostHog/posthog/actions/runs/1',
            charts_run_url: 'https://github.com/PostHog/charts/actions/runs/2',
        },
    })
    assert.match(body, /🟢/)
    assert.match(body, /Healthy/)
    assert.match(body, /auto-disable/)
    assert.match(body, /cancel.*to stop it sooner/)
})

test('renderBody for CANCELED highlights the actor', () => {
    const body = comment.renderBody({
        phase: 'CANCELED',
        fields: { pr: 123, canceled_by: 'matheus-vb', image: 'sha-abc', env: 'dev' },
    })
    assert.match(body, /Canary canceled by @matheus-vb/)
})

test('renderBody for INVALID_INPUT surfaces the reason', () => {
    const body = comment.renderBody({
        phase: 'INVALID_INPUT',
        fields: { pr: 1, reason: 'Invalid weight value: 99' },
    })
    assert.match(body, /Invalid weight value: 99/)
})

test('relativeTime emits "just now" within a minute', () => {
    const recent = new Date().toISOString()
    assert.equal(comment.relativeTime(recent), 'just now')
})

test('expiresIn returns null for null input and a remaining-time string for fresh starts', () => {
    assert.equal(comment.expiresIn(null), null)
    const fresh = new Date().toISOString()
    const result = comment.expiresIn(fresh)
    assert.match(result, /^in 4[78]h \d+m$/)
})

// Guards the /pr-canary status no-charts-run fallback against regressing
// to the buggy `weight > 0 ? HEALTHY : ROLLING_OUT` heuristic. State.yaml
// alone cannot tell HEALTHY from in-flight ROUTING — only the charts run
// conclusion can. When the charts run can't be located, derivePhase MUST
// still return ROUTING/ROLLING_OUT, never HEALTHY.
test('derivePhase without a charts run never returns HEALTHY', () => {
    const ownedRolling = { enabled: true, pr_number: 100, weight: 0 }
    const ownedRouting = { enabled: true, pr_number: 100, weight: 5 }
    assert.equal(state.derivePhase(ownedRolling, null, 100), 'ROLLING_OUT')
    assert.equal(state.derivePhase(ownedRouting, null, 100), 'ROUTING')
    // also: a weight>0 owned canary with an in-flight run is ROUTING (not HEALTHY)
    assert.equal(state.derivePhase(ownedRouting, { status: 'in_progress' }, 100), 'ROUTING')
})

test('derivePhase ROUTING → HEALTHY transition only on charts run completion', () => {
    const ownedRouting = { enabled: true, pr_number: 100, weight: 5 }
    assert.equal(state.derivePhase(ownedRouting, { status: 'queued' }, 100), 'ROUTING')
    assert.equal(state.derivePhase(ownedRouting, { status: 'in_progress' }, 100), 'ROUTING')
    assert.equal(
        state.derivePhase(ownedRouting, { status: 'completed', conclusion: 'success' }, 100),
        'HEALTHY'
    )
    assert.equal(
        state.derivePhase(ownedRouting, { status: 'completed', conclusion: 'failure' }, 100),
        'FAILED'
    )
    assert.equal(
        state.derivePhase(ownedRouting, { status: 'completed', conclusion: 'cancelled' }, 100),
        'CANCELED'
    )
})

test('renderBody for DISPATCHED includes image, env, weight, and dispatch run link', () => {
    const body = comment.renderBody({
        phase: 'DISPATCHED',
        fields: {
            pr: 123,
            image: 'sha-deadbee',
            env: 'prod-us',
            weight: 3,
            started_by: 'matheus-vb',
            started_at: new Date().toISOString(),
            dispatch_run_url: 'https://github.com/PostHog/posthog/actions/runs/42',
        },
    })
    assert.match(body, /<!-- pr-canary-status phase=DISPATCHED/)
    assert.match(body, /Dispatched to charts/)
    assert.match(body, /sha-deadbee/)
    assert.match(body, /prod-us/)
    assert.match(body, /\| Weight \| `3` \|/)
    assert.match(body, /posthog run/)
    assert.match(body, /Auto-disables/)
})

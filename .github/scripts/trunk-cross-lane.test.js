// Run with: node --test .github/scripts/trunk-cross-lane.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { crossLaneFiles, MAX_FILES } = require('./trunk-cross-lane')

const CONTEXT = {
    products: ['alpha', 'beta'],
    services: ['mcp'],
    isolatedProducts: new Set(['alpha', 'beta']),
    semgrepDomains: new Map(),
    rustInventory: {
        crateNames: new Set(['capture', 'shared']),
        byDir: [
            { dir: 'capture', name: 'capture' },
            { dir: 'shared', name: 'shared' },
        ],
    },
    rustAffectedCrates: ['capture'],
    tachGraph: {
        graph: new Map([
            ['alpha', []],
            ['beta', []],
        ]),
        tachDependents: () => [],
    },
}

for (const [name, files, mixed] of [
    ['Django beside Node', ['posthog/api/event_tracker.py', 'nodejs/src/ingestion/ingestion-consumer.ts'], true],
    ['frontend beside Node', ['frontend/src/scenes/urls.ts', 'nodejs/src/cdp/consumers/cdp-api.ts'], true],
    ['a product backend beside Rust', ['products/alpha/backend/models.py', 'rust/capture/src/router.rs'], true],
    ['Node and Rust together', ['nodejs/src/ingestion/ingestion-consumer.ts', 'rust/capture/src/router.rs'], false],
    ['Django and frontend together', ['posthog/api/event_tracker.py', 'frontend/src/scenes/urls.ts'], false],
    ['Node alone', ['nodejs/src/ingestion/ingestion-consumer.ts'], false],
    // Markdown claims no lane, so a README beside Node code is not a mix.
    ['prose beside Node', ['README.md', 'nodejs/src/ingestion/ingestion-consumer.ts'], false],
    [
        'a Python workflow beside a Rust workflow',
        ['.github/workflows/ci-backend.yml', '.github/workflows/ci-rust.yml'],
        false,
    ],
]) {
    test(`${name} is ${mixed ? '' : 'not '}a cross-lane change`, () => {
        assert.equal(crossLaneFiles(files, CONTEXT).mixed, mixed)
    })
}

test('names the files on each side so the author knows what to split', () => {
    const verdict = crossLaneFiles(
        ['posthog/api/event_tracker.py', 'nodejs/src/ingestion/ingestion-consumer.ts', 'README.md'],
        CONTEXT
    )
    assert.deepEqual(verdict.heavyFiles, ['posthog/api/event_tracker.py'])
    assert.deepEqual(verdict.lightFiles, ['nodejs/src/ingestion/ingestion-consumer.ts'])
})

test('a file that claims both sides by rule is not counted on either', () => {
    const verdict = crossLaneFiles(['hogli.yaml', 'nodejs/src/ingestion/ingestion-consumer.ts'], CONTEXT)
    assert.equal(verdict.mixed, false)
    assert.deepEqual(verdict.heavyFiles, [])
})

test('gives no verdict for an empty or oversized change set', () => {
    assert.equal(crossLaneFiles([], CONTEXT), null)
    const huge = Array.from({ length: MAX_FILES + 1 }, (_, i) => `posthog/file_${i}.py`)
    assert.equal(crossLaneFiles(huge, CONTEXT), null)
})

test('logs the file that could not be classified rather than failing silently', (t) => {
    const errors = t.mock.method(console, 'error', () => {})
    const broken = { ...CONTEXT, isolatedProducts: undefined }
    assert.equal(crossLaneFiles(['products/alpha/backend/models.py'], broken), null)
    assert.match(errors.mock.calls[0].arguments[0], /products\/alpha\/backend\/models\.py/)
})

test('gives no verdict when any file cannot be enumerated', (t) => {
    t.mock.method(console, 'error', () => {})
    const noCrates = { ...CONTEXT, rustInventory: null }
    assert.equal(crossLaneFiles(['posthog/api/event_tracker.py', 'rust/capture/src/router.rs'], noCrates), null)
})

test('a file that falls through every lane rule gives no verdict, unless the other files already prove a mix', (t) => {
    t.mock.method(console, 'error', () => {})
    assert.equal(crossLaneFiles(['posthog/api/event_tracker.py', 'some-new-toplevel/thing.go'], CONTEXT), null)
    const proven = crossLaneFiles(
        ['posthog/api/event_tracker.py', 'nodejs/src/ingestion/ingestion-consumer.ts', 'some-new-toplevel/thing.go'],
        CONTEXT
    )
    assert.equal(proven.mixed, true)
})

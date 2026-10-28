import assert from 'node:assert/strict'
import { test } from 'node:test'

import { authPrototypeBootBytes } from './auth-prototype-graph.mjs'

const entry = 'src/auth-prototype/authPrototypeEntry.tsx'
const required = ['src/auth-prototype/AuthPrototype.tsx', 'src/initKea.ts', 'src/loadPostHogJS.tsx']

function fixture() {
    return {
        inputs: {
            [entry]: { imports: required.map((path) => ({ path, kind: 'dynamic-import' })) },
        },
        outputs: {
            'dist/entry.js': {
                entryPoint: entry,
                bytes: 10,
                cssBundle: 'dist/entry.css',
                imports: [
                    { path: 'dist/shared.js', kind: 'import-statement' },
                    { path: 'dist/app.js', kind: 'dynamic-import' },
                ],
            },
            'dist/app.js': {
                entryPoint: required[0],
                bytes: 20,
                cssBundle: 'dist/app.css',
                imports: [
                    { path: 'dist/shared.js', kind: 'import-statement' },
                    { path: 'dist/later.js', kind: 'dynamic-import' },
                ],
            },
            'dist/kea.js': {
                entryPoint: required[1],
                bytes: 30,
                imports: [{ path: 'dist/shared.js', kind: 'import-statement' }],
            },
            'dist/posthog.js': { entryPoint: required[2], bytes: 40 },
            'dist/shared.js': { bytes: 5 },
            'dist/later.js': { bytes: 1000, cssBundle: 'dist/later.css' },
            'dist/entry.css': { bytes: 3 },
            'dist/app.css': { bytes: 4 },
            'dist/later.css': { bytes: 1000 },
        },
    }
}

test('counts the deduplicated boot graph, including CSS, but not later imports', () => {
    assert.deepEqual(authPrototypeBootBytes(fixture()), { bytes: 112, files: 7 })
})

for (const missing of required) {
    test(`requires the ${missing} dynamic import`, () => {
        const meta = fixture()
        meta.inputs[entry].imports = meta.inputs[entry].imports.filter((item) => item.path !== missing)
        assert.throws(() => authPrototypeBootBytes(meta), /must dynamically import/)
    })
}

test('fails when a required output or stylesheet is missing', () => {
    const meta = fixture()
    delete meta.outputs['dist/posthog.js']
    assert.throws(() => authPrototypeBootBytes(meta), /No auth prototype output chunk/)

    const other = fixture()
    delete other.outputs['dist/app.css']
    assert.throws(() => authPrototypeBootBytes(other), /No auth prototype CSS output/)
})

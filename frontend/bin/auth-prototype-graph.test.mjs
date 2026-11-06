import assert from 'node:assert/strict'
import { test } from 'node:test'

import { AUTH_PROTOTYPE_BOOT, authPrototypeBootShare } from './auth-prototype-graph.mjs'
import { LOGGED_OUT_BOOT } from './bootEntries.mjs'

function report() {
    return {
        roots: [
            { root: 'src/scenes/AuthenticatedShell.tsx', bytes: 1, files: 1 },
            { root: LOGGED_OUT_BOOT.join(' + '), bytes: 200, files: 9 },
            { root: AUTH_PROTOTYPE_BOOT.join(' + '), bytes: 50, files: 4 },
        ],
    }
}

test('compares the auth prototype root with the logged-out boot root of the same report', () => {
    assert.deepEqual(authPrototypeBootShare(report()), { bytes: 50, files: 4, currentBytes: 200, share: 0.25 })
})

for (const [missing, message] of [
    [LOGGED_OUT_BOOT, /No logged-out boot root/],
    [AUTH_PROTOTYPE_BOOT, /No auth prototype root/],
]) {
    test(`fails when the report has no ${missing[0]} root`, () => {
        const withoutRoot = report()
        withoutRoot.roots = withoutRoot.roots.filter((item) => item.root !== missing.join(' + '))
        assert.throws(() => authPrototypeBootShare(withoutRoot), message)
    })
}

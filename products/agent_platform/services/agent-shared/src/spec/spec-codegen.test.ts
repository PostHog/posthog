import { readdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { basename, dirname, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

import { GENERATED_ARTIFACTS } from './spec-codegen'

/**
 * Asserts each checked-in artifact parses to the same data its TS source produces
 * (parsed, not bytes — formatter-immune), so a source edited without regenerating
 * goes red. Set UPDATE_GENERATED=1 to (re)write the files instead of asserting.
 */
describe('spec generated artifacts', () => {
    // Floor: `it.each([])` registers zero tests and passes green — a vacuous guard.
    // Assert the registry is populated so an emptied `GENERATED_ARTIFACTS` fails loud.
    it('the artifact registry is non-empty (guard is non-vacuous)', () => {
        expect(GENERATED_ARTIFACTS.length).toBeGreaterThanOrEqual(3)
    })

    // Registry↔disk bijection: the freshness check iterates the registry, so a file
    // dropped from it but still on disk (and imported by generated.py) drifts
    // undetected. Assert the sets match.
    it('every generated file on disk is registered, and vice versa (no orphans)', () => {
        const dir = dirname(GENERATED_ARTIFACTS[0].path)
        const onDisk = readdirSync(dir)
            .filter((f) => f.endsWith('.generated.json'))
            .sort()
        const registered = GENERATED_ARTIFACTS.map((a) => basename(a.path)).sort()
        expect(onDisk).toEqual(registered)
    })

    if (process.env.UPDATE_GENERATED) {
        for (const artifact of GENERATED_ARTIFACTS) {
            // Atomic write: an interrupted regen must not leave a half-file that
            // Django then loads at import time (see generated.py `_load`).
            const tmp = `${artifact.path}.tmp`
            writeFileSync(tmp, artifact.content())
            renameSync(tmp, artifact.path)
        }
    }

    it.each(GENERATED_ARTIFACTS.map((a) => [relative(process.cwd(), a.path), a] as const))(
        'checked-in %s matches its TS source (regenerate with UPDATE_GENERATED=1)',
        (_name, artifact) => {
            expect(JSON.parse(readFileSync(artifact.path, 'utf-8'))).toEqual(JSON.parse(artifact.content()))
        }
    )
})

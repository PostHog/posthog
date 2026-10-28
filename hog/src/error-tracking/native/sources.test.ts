import { describe, expect, test } from 'bun:test'
import { mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { collectSources, zipRelativePaths } from './sources'

// The parity fixtures name no two sources alike and hold no symlinks, so these cases cover the
// collision rounds and the read refusals that posthog-cli's own unit tests cover.
describe('source bundles', () => {
    test.each([
        ['distinct names stay file names', ['/src/a.c', '/src/b.c'], ['a.c', 'b.c']],
        [
            'shared names take parents until they differ',
            ['/a/x/f.c', '/b/x/f.c', '/c/g.c'],
            ['a/x/f.c', 'b/x/f.c', 'g.c'],
        ],
        [
            'dot components never reach a zip name',
            ['/a/../conflict.go', '/a/b/conflict.go'],
            ['a/conflict.go', 'b/conflict.go'],
        ],
        ['a path with no file name is unknown', ['/'], ['unknown']],
    ])('%s', (_name, paths, expected) => {
        expect(zipRelativePaths(paths)).toEqual(expected)
    })

    test('a symlinked source is refused, and the real file is read', () => {
        const folder = mkdtempSync(join(tmpdir(), 'hog-sources-'))
        writeFileSync(join(folder, 'secret'), 'sensitive')
        symlinkSync(join(folder, 'secret'), join(folder, 'legit.go'))
        const warnings: string[] = []

        const bundle = collectSources([join(folder, 'legit.go'), join(folder, 'secret')], warnings)

        expect([...bundle.manifest.keys()]).toEqual([join(folder, 'secret')])
        expect(warnings).toEqual([expect.stringContaining('path is a symlink')])
    })
})

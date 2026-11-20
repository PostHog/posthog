import { afterAll, describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { extractSymbolSet } from './symbols'
import { MAX_FILE_SIZE } from './upload'
import { Worker } from './worker'

const BINARY = join(import.meta.dir, '../../test/parity/native/bin/linux/checkout')
const SOURCE_PREFIX = 'Checkout/__source/'

// The parity fixtures name no two sources alike and hold no symlinks, so these cases cover the
// collision rounds and the read refusals that posthog-cli's own unit tests cover.
describe('source bundles', () => {
    const worker = new Worker()

    afterAll(() => worker.close())

    async function pack(sources: string[], folder: string | null): ReturnType<Worker['packNative']> {
        const [file] = await worker.nativeCandidates([BINARY])
        if (!file || !('candidates' in file) || !file.candidates[0] || !('id' in file.candidates[0])) {
            throw new Error('The fixture binary gave no candidate.')
        }
        const { id, debugId } = file.candidates[0]
        return worker.packNative([sources], [{ id, sources: 0, chunkId: debugId, dsym: false }], folder, MAX_FILE_SIZE)
    }

    test.each([
        ['distinct names stay file names', ['src/a.c', 'src/b.c'], ['a.c', 'b.c']],
        ['shared names take parents until they differ', ['a/x/f.c', 'b/x/f.c', 'c/g.c'], ['a/x/f.c', 'b/x/f.c', 'g.c']],
        [
            'dot components never reach a zip name',
            ['a/../a/conflict.go', 'a/b/conflict.go'],
            ['a/conflict.go', 'b/conflict.go'],
        ],
    ])('%s', async (_name, sources, expected) => {
        const folder = mkdtempSync(join(tmpdir(), 'hog-sources-'))
        for (const source of sources) {
            mkdirSync(dirname(join(folder, source)), { recursive: true })
            writeFileSync(join(folder, source), source)
        }

        const packed = await pack(
            sources.map((source) => `${folder}/${source}`),
            folder
        )

        const container = readFileSync(packed.containers[0]!.path!)
        const { files } = extractSymbolSet(container, 'Checkout', 'out', folder, true)
        const sourceFolder = join('out', SOURCE_PREFIX)
        const names = files
            .filter((file) => file.startsWith(sourceFolder))
            .map((file) => file.slice(sourceFolder.length))
        expect(names).toEqual(['manifest.json', ...expected])
    })

    test.skipIf(process.platform === 'win32')('a FIFO is refused without waiting for a writer', async () => {
        const folder = mkdtempSync(join(tmpdir(), 'hog-sources-'))
        Bun.spawnSync(['mkfifo', join(folder, 'pipe.c')])

        const packed = await pack([join(folder, 'pipe.c')], null)

        expect(packed.unreadable).toEqual([[{ path: join(folder, 'pipe.c'), message: 'not a regular file' }]])
    })

    test('a symlinked source is refused, and the real file is read', async () => {
        const folder = mkdtempSync(join(tmpdir(), 'hog-sources-'))
        writeFileSync(join(folder, 'secret'), 'sensitive')
        symlinkSync(join(folder, 'secret'), join(folder, 'legit.go'))

        const packed = await pack([join(folder, 'legit.go'), join(folder, 'secret')], folder)

        expect(packed.unreadable).toEqual([[{ path: join(folder, 'legit.go'), message: 'path is a symlink' }]])
        const container = readFileSync(packed.containers[0]!.path!)
        const { files } = extractSymbolSet(container, 'Checkout', 'out', folder, true)
        expect(files).toContain(join('out', SOURCE_PREFIX, 'secret'))
        expect(files).not.toContain(join('out', SOURCE_PREFIX, 'legit.go'))
    })
})

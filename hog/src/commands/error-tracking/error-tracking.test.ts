import { describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { runHog } from '@/testing'

import { SMALL_MAPPING } from '../../../test/parity/fixtures'

function project(files: Record<string, string>): string {
    const folder = mkdtempSync(join(tmpdir(), 'hog-et-'))
    for (const [path, contents] of Object.entries(files)) {
        mkdirSync(join(folder, path, '..'), { recursive: true })
        writeFileSync(join(folder, path), contents)
    }
    return folder
}

describe('hog error-tracking upload', () => {
    test('--dry-run plans uploads from posthog.json without credentials', async () => {
        const folder = project({
            'posthog.json': JSON.stringify({
                errorTracking: {
                    release: { name: 'app', version: '2.0' },
                    sources: [{ path: 'build', mapId: 'map-1' }],
                },
            }),
            'build/mapping.txt': SMALL_MAPPING,
            'build/notes.txt': 'not a mapping',
        })
        const result = await runHog(['et', 'upload', '--dry-run'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({
            dryRun: true,
            release: { name: 'app', version: '2.0', id: null },
            symbolSets: [
                {
                    path: 'build/mapping.txt',
                    kind: 'proguard',
                    chunkId: 'map-1',
                    contentHash: contentHash(
                        writeSymbolData(SymbolDataType.ProguardMapping, Buffer.from(SMALL_MAPPING))
                    ),
                    size: expect.any(Number),
                    status: 'planned',
                },
            ],
        })
    })

    test.each([
        ['a ProGuard mapping without a map ID', ['mapping.txt'], 2, 'map_id_required'],
        ['a file hog cannot place', ['notes.txt'], 1, 'unknown_artifact'],
        ['no paths and no posthog.json', [], 2, 'no_paths'],
    ])('%s fails with a hint', async (_name, paths, exitCode, code) => {
        const folder = project({ 'mapping.txt': SMALL_MAPPING, 'notes.txt': 'hello' })
        const result = await runHog(['et', 'upload', '--dry-run', ...paths], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })
})

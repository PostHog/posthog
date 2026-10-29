import { describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { stripCredentials } from '@/error-tracking/git'
import { runHog } from '@/testing'

import { GIT_REPO, SMALL_MAPPING } from '../../../test/parity/fixtures'

function project(files: Record<string, string>): string {
    const folder = mkdtempSync(join(tmpdir(), 'hog-et-'))
    for (const [path, contents] of Object.entries(files)) {
        mkdirSync(join(folder, path, '..'), { recursive: true })
        writeFileSync(join(folder, path), contents)
    }
    return folder
}

describe('hog error-tracking upload', () => {
    test.each([
        ['the map ID from posthog.json', [], 'map-1'],
        ['--map-id over the one in posthog.json', ['--map-id', 'map-2'], 'map-2'],
    ])('--dry-run plans uploads from posthog.json without credentials, with %s', async (_name, flags, chunkId) => {
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
        const result = await runHog(['et', 'upload', '--dry-run', ...flags], {
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
                    chunkId,
                    contentHash: contentHash(
                        writeSymbolData(SymbolDataType.ProguardMapping, Buffer.from(SMALL_MAPPING))
                    ),
                    size: expect.any(Number),
                    status: 'planned',
                },
            ],
        })
    })

    test('--dry-run reads the release from the repository a symlinked mapping points into', async () => {
        const repository = project({ ...GIT_REPO, 'app/mapping.txt': SMALL_MAPPING })
        const outside = project({})
        symlinkSync(join(repository, 'app/mapping.txt'), join(outside, 'mapping.txt'))
        const result = await runHog(['et', 'upload', '--dry-run', 'mapping.txt', '--map-id', 'map-1'], {
            env: { CLAUDECODE: '1' },
            cwd: outside,
            useDisk: true,
        })
        expect(result.json().release).toEqual({
            name: 'example-app',
            version: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
            id: null,
        })
    })

    test.each([
        ['git@github.com:org/repo.git', 'git@github.com:org/repo.git'],
        ['ghp_token@github.com:org/repo.git', 'github.com:org/repo.git'],
        ['https://x-access-token:secret@github.com/org/repo.git', 'https://github.com/org/repo.git'],
        ['git@github.com:org/repo@secret.git', undefined],
    ])('the release keeps no credential from the remote %s', (remote, stored) => {
        expect(stripCredentials(remote)).toBe(stored)
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

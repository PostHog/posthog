import type { Scenario } from './fake-server'
import { GIT_REPO, mappingOfSize, SMALL_MAPPING } from './fixtures'

export interface ParityScenario {
    name: string
    server: Scenario
    files: Record<string, string | Uint8Array>
    rust: string[]
    hog: string[]
    // Run this many times against the same server and compare only the last run, to cover re-uploads.
    runs?: number
}

const release = ['--release-name', 'com.example.app', '--release-version', '1.0', '--build', '7']

const proguard = (
    name: string,
    server: Scenario,
    options: Partial<ParityScenario> & { args?: string[]; file?: string } = {}
): ParityScenario => {
    const file = options.file ?? 'mapping.txt'
    const args = options.args ?? []
    return {
        name: `proguard-${name}`,
        server,
        files: options.files ?? { [file]: SMALL_MAPPING },
        rust: ['proguard', 'upload', '--path', file, '--map-id', `map-${name}`, ...args],
        hog: ['error-tracking', 'upload', file, '--map-id', `map-${name}`, ...args],
        runs: options.runs,
    }
}

export const SCENARIOS: ParityScenario[] = [
    proguard('fresh', 'fresh', { args: release }),
    proguard('no-release', 'fresh'),
    proguard('release-from-git', 'fresh', {
        file: 'app/mapping.txt',
        files: { ...GIT_REPO, 'app/mapping.txt': SMALL_MAPPING },
    }),
    proguard('already-present', 'fresh', { args: release, runs: 2 }),
    proguard('post-only', 'post-only', { args: release }),
    proguard('hash-mismatch', 'hash-mismatch', { args: release }),
    proguard('hash-mismatch-force', 'hash-mismatch', { args: [...release, '--force'] }),
    proguard('hash-mismatch-skip', 'hash-mismatch', { args: [...release, '--skip-on-conflict'] }),
    proguard('release-mismatch', 'release-mismatch', { args: release }),
    proguard('check-403', 'check-403', { args: release }),
    proguard('start-500-once', 'start-500-once', { args: release }),
    proguard('block-multiple', 'fresh', { files: { 'mapping.txt': mappingOfSize(2 * 128 * 1024) } }),
    proguard('bom-crlf', 'fresh', { files: { 'mapping.txt': `﻿${SMALL_MAPPING.replaceAll('\n', '\r\n')}` } }),
]

// What compile.ts, build-worker.ts and package.ts agree on: the arguments, where each target's
// files go, and how a build step runs.

import { join, resolve } from 'node:path'

import { findTarget, TARGETS, type Target } from '../src/updates/targets'
import { parseVersion } from '../src/updates/version'

export const HOG_ROOT = resolve(import.meta.dir, '..')
export const RELEASE_FOLDER = join(HOG_ROOT, 'dist/release')

export function targetFolder(root: string, target: Target): string {
    return join(resolve(root), 'bin', target.id)
}

export const BUILD_OPTIONS = {
    target: { type: 'string', multiple: true },
    version: { type: 'string' },
} as const

export function buildTargets(ids: string[] | undefined, version: string | undefined): readonly Target[] {
    if (version !== undefined && !parseVersion(version)) {
        console.error(`--version ${version} isn't a semver version.`)
        process.exit(1)
    }
    return ids ? ids.map(findTarget) : TARGETS
}

export async function run(command: string[], cwd: string, env: Record<string, string> = {}): Promise<void> {
    const child = Bun.spawn(command, { cwd, env: { ...process.env, ...env }, stdout: 'inherit', stderr: 'inherit' })
    if ((await child.exited) !== 0) {
        throw new Error(`${command.join(' ')} failed`)
    }
}

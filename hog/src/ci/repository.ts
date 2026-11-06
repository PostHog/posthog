import { dirname, isAbsolute, join, resolve } from 'node:path'

import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import { WORKLOAD_PROVIDERS, type WorkloadProvider } from './providers'

export interface Repository {
    root: string
    remote: string | undefined
}

async function findGitRoot(runtime: Runtime): Promise<{ root: string; gitPath: string } | undefined> {
    let folder = runtime.cwd()
    for (;;) {
        const gitPath = join(folder, '.git')
        if (await runtime.exists(gitPath)) {
            return { root: folder, gitPath }
        }
        const parent = dirname(folder)
        if (parent === folder) {
            return undefined
        }
        folder = parent
    }
}

// A linked worktree has a `.git` file that points at its folder inside the main repository, whose
// `commondir` file points at the folder that holds the shared config.
async function configPath(runtime: Runtime, gitPath: string): Promise<string> {
    if (await runtime.isDirectory(gitPath)) {
        return join(gitPath, 'config')
    }
    const pointer = (await runtime.readFile(gitPath)).match(/^gitdir:\s*(.+)$/m)?.[1]?.trim()
    if (!pointer) {
        return join(gitPath, 'config')
    }
    const gitDir = isAbsolute(pointer) ? pointer : resolve(dirname(gitPath), pointer)
    const common = await runtime.readFile(join(gitDir, 'commondir')).then(
        (text) => text.trim(),
        () => undefined
    )
    return join(common ? resolve(gitDir, common) : gitDir, 'config')
}

function originUrl(config: string): string | undefined {
    let inOrigin = false
    for (const raw of config.split(/\r?\n/)) {
        const line = raw.trim()
        if (line.startsWith('[')) {
            inOrigin = /^\[remote\s+"origin"\]$/.test(line)
            continue
        }
        const url = inOrigin ? line.match(/^url\s*=\s*(.+)$/)?.[1]?.trim() : undefined
        if (url) {
            return url.replace(/^"(.*)"$/, '$1')
        }
    }
    return undefined
}

export async function readRepository(runtime: Runtime): Promise<Repository | undefined> {
    const found = await findGitRoot(runtime)
    if (!found) {
        return undefined
    }
    const config = await runtime.readFile(await configPath(runtime, found.gitPath)).catch(() => '')
    return { root: found.root, remote: originUrl(config) }
}

export function pickProviderHint(providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS): string {
    return `Pass --provider with one of: ${providers.map((provider) => provider.key).join(', ')}.`
}

export async function detectRepositoryProvider(
    runtime: Runtime,
    repository: Repository | undefined,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): Promise<WorkloadProvider> {
    const pick = pickProviderHint(providers)
    if (repository === undefined) {
        throw new HogError('provider_not_detected', "hog couldn't find a git repository here.", pick, EXIT_USAGE)
    }
    const matches: WorkloadProvider[] = []
    const { root, remote } = repository
    for (const provider of providers) {
        if (remote === undefined || provider.nameFromRemote(remote) === undefined) {
            continue
        }
        const configured = await Promise.all(provider.configPaths.map((path) => runtime.exists(join(root, path))))
        if (configured.some(Boolean)) {
            matches.push(provider)
        }
    }
    if (matches.length === 1) {
        return matches[0]!
    }
    const why =
        matches.length === 0
            ? "hog couldn't tell which CI provider runs this repository."
            : `This repository has CI config for ${matches.map((provider) => provider.name).join(' and ')}.`
    throw new HogError('provider_not_detected', why, pick, EXIT_USAGE)
}

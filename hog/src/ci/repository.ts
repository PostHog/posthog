import { dirname, isAbsolute, join, resolve } from 'node:path'

import { EXIT_USAGE, HogError } from '@/core/errors'
import { findGitRoot } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { parseRemoteUrls, stripCredentials } from '@/error-tracking/git'

import { WORKLOAD_PROVIDERS, type WorkloadProvider } from './providers/registry'

export interface Repository {
    root: string
    remote: string | undefined
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

export async function readRepository(runtime: Runtime): Promise<Repository | undefined> {
    const found = await findGitRoot(runtime)
    if (!found) {
        return undefined
    }
    const config = await runtime.readFile(await configPath(runtime, found.gitPath)).catch(() => '')
    const remotes = parseRemoteUrls(config)
    // Only origin, so a checkout of someone else's repository never asks to trust theirs.
    const url = remotes.find(([name]) => name === 'origin')?.[1]
    // A remote URL can carry a token, and the name read from it goes to PostHog.
    return { root: found.root, remote: url === undefined ? undefined : stripCredentials(url) }
}

function pickProviderHint(): string {
    return `Pass --provider with one of: ${WORKLOAD_PROVIDERS.map((provider) => provider.key).join(', ')}.`
}

export function providerByKey(key: string): WorkloadProvider {
    const provider = WORKLOAD_PROVIDERS.find((candidate) => candidate.key === key)
    if (!provider) {
        throw new HogError(
            'unknown_provider',
            `hog doesn't support the CI provider ${key}.`,
            pickProviderHint(),
            EXIT_USAGE
        )
    }
    return provider
}

export async function detectRepositoryProvider(
    runtime: Runtime,
    repository: Repository | undefined
): Promise<WorkloadProvider> {
    const pick = pickProviderHint()
    if (repository === undefined) {
        throw new HogError('provider_not_detected', "hog couldn't find a git repository here.", pick, EXIT_USAGE)
    }
    const matches: WorkloadProvider[] = []
    const { root, remote } = repository
    for (const provider of WORKLOAD_PROVIDERS) {
        if (remote === undefined || provider.nameFromRemote(remote) === undefined) {
            continue
        }
        if (await runtime.exists(join(root, provider.configPath))) {
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

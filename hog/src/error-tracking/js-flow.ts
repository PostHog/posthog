import { HogError } from '@/core/errors'
import type { Env } from '@/core/runtime'

import { GitError, gitInfo, type GitInfo } from './git'
import { packVersion, type ReleaseFields } from './release'
import { uuidv7 } from './upload'

export type InjectAction = 'injected' | 'release_updated' | 'unchanged'

export const randomChunkId = (now: () => number) => (): string => uuidv7(now())

export interface JsRelease {
    name: string
    version: string
    git: GitInfo | undefined
}

export function resolveJsRelease(
    fields: ReleaseFields,
    env: Env,
    cwd: string,
    warnings: string[]
): JsRelease | undefined {
    let name = fields.name
    let version = packVersion(fields.version, fields.build)
    const complete = name !== undefined && version !== undefined
    let git: GitInfo | undefined
    try {
        git = gitInfo(env, cwd)
    } catch (error) {
        if (!(error instanceof GitError)) {
            throw error
        }
        if (!complete) {
            throw new HogError(
                'git_failed',
                `hog couldn't read the git repository for the release: ${error.message}`,
                'Pass --release-name and --release-version.'
            )
        }
        warnings.push(`Skipping git metadata for the release: ${error.message}`)
    }
    if (git) {
        name ??= git.repo_name
        version ??= git.commit_id
    }
    return name !== undefined && version !== undefined ? { name, version, git } : undefined
}

export function releaseRequested(fields: ReleaseFields): boolean {
    return fields.name !== undefined || fields.version !== undefined || fields.build !== undefined
}

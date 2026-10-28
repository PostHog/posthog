import { existsSync, readFileSync, realpathSync, statSync } from 'node:fs'
import { basename, dirname, isAbsolute, join } from 'node:path'

import type { Env } from '@/core/runtime'

// A port of posthog-cli's `utils/git.rs`. The repo name and commit become the default release name
// and version, and those decide the release's hash id, so they must come out exactly as in Rust.
export interface GitInfo {
    remote_url?: string
    repo_name?: string
    branch: string
    commit_id: string
}

interface RepositoryPaths {
    gitDir: string
    commonDir: string
    worktreeDir: string
}

function envValue(env: Env, name: string): string | undefined {
    const value = env[name]?.trim()
    return value ? value : undefined
}

function fromGitHub(env: Env): GitInfo | undefined {
    if (!envValue(env, 'GITHUB_ACTIONS')) {
        return undefined
    }
    const branch = envValue(env, 'GITHUB_REF_NAME')
    const commit = envValue(env, 'GITHUB_SHA')
    const repository = envValue(env, 'GITHUB_REPOSITORY')
    const server = envValue(env, 'GITHUB_SERVER_URL')
    if (!branch || !commit || !repository || !server) {
        return undefined
    }
    return {
        remote_url: `${server}/${repository}.git`,
        repo_name: repository.split('/').at(-1),
        branch,
        commit_id: commit,
    }
}

const VERCEL_PROVIDERS: Record<string, string> = {
    github: 'https://github.com',
    gitlab: 'https://gitlab.com',
    bitbucket: 'https://bitbucket.org',
}

function fromVercel(env: Env): GitInfo | undefined {
    if (!envValue(env, 'VERCEL')) {
        return undefined
    }
    const branch = envValue(env, 'VERCEL_GIT_COMMIT_REF')
    const commit = envValue(env, 'VERCEL_GIT_COMMIT_SHA')
    const slug = envValue(env, 'VERCEL_GIT_REPO_SLUG')
    if (!branch || !commit || !slug) {
        return undefined
    }
    const provider = VERCEL_PROVIDERS[envValue(env, 'VERCEL_GIT_PROVIDER') ?? '']
    const owner = envValue(env, 'VERCEL_GIT_REPO_OWNER')
    const info: GitInfo = { repo_name: slug, branch, commit_id: commit }
    if (provider && owner) {
        info.remote_url = `${provider}/${owner}/${slug}.git`
    }
    return info
}

// Rust's `Path::is_dir` and `is_file` read any error as false. A walk that starts at a file looks
// for `<file>/.git`, which fails with ENOTDIR rather than ENOENT.
function stat(path: string): ReturnType<typeof statSync> | undefined {
    try {
        return statSync(path)
    } catch {
        return undefined
    }
}

const isDirectory = (path: string): boolean => stat(path)?.isDirectory() ?? false
const isFile = (path: string): boolean => stat(path)?.isFile() ?? false

function readText(path: string): string | undefined {
    try {
        return readFileSync(path, 'utf8')
    } catch {
        return undefined
    }
}

function canonical(path: string): string {
    try {
        return realpathSync(path)
    } catch {
        return path
    }
}

function findRepository(start: string): RepositoryPaths | undefined {
    let current = start
    for (;;) {
        const gitPath = join(current, '.git')
        if (isDirectory(gitPath)) {
            const gitDir = canonical(gitPath)
            return { gitDir, commonDir: gitDir, worktreeDir: current }
        }
        if (isFile(gitPath)) {
            // A worktree or submodule: `.git` is a file that points at the real git dir.
            const pointer = readText(gitPath)?.trim()
            if (!pointer?.startsWith('gitdir:')) {
                return undefined
            }
            const target = pointer.slice('gitdir:'.length).trim()
            const gitDir = canonical(isAbsolute(target) ? target : join(dirname(gitPath), target))
            const commondir = readText(join(gitDir, 'commondir'))?.trim()
            const commonDir =
                commondir === undefined
                    ? gitDir
                    : canonical(isAbsolute(commondir) ? commondir : join(gitDir, commondir))
            return { gitDir, commonDir, worktreeDir: current }
        }
        const parent = dirname(current)
        if (parent === current) {
            return undefined
        }
        current = parent
    }
}

function configPaths({ gitDir, commonDir }: RepositoryPaths): string[] {
    const paths = [join(gitDir, 'config.worktree')]
    if (commonDir !== gitDir) {
        paths.push(join(commonDir, 'config'))
    }
    paths.push(join(gitDir, 'config'))
    return paths
}

// Index of the `]` that closes a section header. A quoted subsection can hold its own `]`.
function sectionHeaderEnd(line: string): number | undefined {
    let inQuotes = false
    let escaped = false
    for (let index = 0; index < line.length; index++) {
        const char = line[index]
        if (escaped) {
            escaped = false
        } else if (char === '\\') {
            escaped = true
        } else if (char === '"') {
            inQuotes = !inQuotes
        } else if (char === ']' && !inQuotes) {
            return index
        }
    }
    return undefined
}

function stripComment(line: string): string {
    let inQuotes = false
    let escaped = false
    for (let index = 0; index < line.length; index++) {
        const char = line[index]
        if (escaped) {
            escaped = false
        } else if (char === '\\') {
            escaped = true
        } else if (char === '"') {
            inQuotes = !inQuotes
        } else if ((char === '#' || char === ';') && !inQuotes) {
            return line.slice(0, index).trimEnd()
        }
    }
    return line
}

// Git keeps the character after `\` in a subsection name and drops the backslash.
function unescapeSubsection(name: string): string {
    let out = ''
    for (let index = 0; index < name.length; index++) {
        if (name[index] === '\\') {
            index++
            out += name[index] ?? ''
        } else {
            out += name[index]
        }
    }
    return out
}

function remoteName(header: string): string | undefined {
    const trimmed = header.trim()
    const quote = trimmed.indexOf('"')
    if (quote === -1 || trimmed.slice(0, quote).trim().toLowerCase() !== 'remote') {
        return undefined
    }
    const subsection = trimmed.slice(quote + 1)
    if (!subsection.endsWith('"')) {
        return undefined
    }
    const name = unescapeSubsection(subsection.slice(0, -1))
    return name || undefined
}

function unescapeValue(value: string): string {
    let out = ''
    for (let index = 0; index < value.length; index++) {
        const char = value[index]
        if (char === '"') {
            continue
        }
        if (char === '\\') {
            const next = value[index + 1]
            if (next === '"' || next === '\\') {
                out += next
                index++
            } else if (next === undefined) {
                out += '\\'
            } else {
                out += `\\${next}`
                index++
            }
            continue
        }
        out += char
    }
    return out
}

function parseRemoteUrls(config: string): [string, string][] {
    const remotes: [string, string][] = []
    let current: string | undefined
    // Rust's `str::lines` splits on `\n` and drops one trailing `\r` per line.
    for (const rawLine of config.split('\n')) {
        let line = stripComment(rawLine.replace(/\r$/, '').trim())
        if (line.startsWith('[')) {
            const end = sectionHeaderEnd(line)
            if (end === undefined) {
                current = undefined
                continue
            }
            current = remoteName(line.slice(1, end))
            line = line.slice(end + 1).trim()
        }
        if (current === undefined) {
            continue
        }
        const equals = line.indexOf('=')
        if (equals === -1 || line.slice(0, equals).trim().toLowerCase() !== 'url') {
            continue
        }
        const url = unescapeValue(line.slice(equals + 1).trim())
        if (url) {
            remotes.push([current, url])
        }
    }
    return remotes
}

function findRemoteUrl(paths: RepositoryPaths): string | undefined {
    const remotes: [string, string][] = []
    for (const path of configPaths(paths)) {
        const content = readText(path)
        if (content === undefined) {
            continue
        }
        for (const [name, url] of parseRemoteUrls(content)) {
            if (!remotes.some(([known]) => known === name)) {
                remotes.push([name, url])
            }
        }
    }
    return (remotes.find(([name]) => name === 'origin') ?? remotes[0])?.[1]
}

// Drops anything that can carry a credential (userinfo, query, fragment) before the URL is stored,
// and refuses URLs whose `@` sits where no parser can tell a token from a path.
export function stripCredentials(url: string): string | undefined {
    const cut = url.search(/[?#]/)
    const trimmed = cut === -1 ? url : url.slice(0, cut)
    if (url.includes('@') && !trimmed.includes('@')) {
        return undefined
    }
    if (!trimmed.includes('://')) {
        const colon = trimmed.indexOf(':')
        const path = colon === -1 ? '' : trimmed.slice(colon + 1)
        return path.includes('@') ? undefined : trimmed
    }
    let parsed: URL
    try {
        parsed = new URL(trimmed)
    } catch {
        return trimmed.includes('@') ? undefined : trimmed
    }
    if (parsed.pathname.includes('@')) {
        return undefined
    }
    if (parsed.username === '' && parsed.password === '') {
        return trimmed
    }
    parsed.username = ''
    parsed.password = ''
    return parsed.toString()
}

function remoteUrl(paths: RepositoryPaths): string | undefined {
    const url = findRemoteUrl(paths)
    const sanitized = url === undefined ? undefined : stripCredentials(url)
    if (sanitized === undefined) {
        return undefined
    }
    return sanitized.endsWith('.git') ? sanitized : `${sanitized}.git`
}

function repoName(paths: RepositoryPaths): string | undefined {
    const url = findRemoteUrl(paths)
    const sanitized = url === undefined ? undefined : stripCredentials(url)
    if (sanitized !== undefined) {
        // Rust's `trim_end_matches(".git")` removes every trailing `.git`, so `x.git.git` becomes `x`.
        const name = (sanitized.split('/').at(-1) ?? '').replace(/(\.git)+$/, '')
        if (name) {
            return name
        }
    }
    return basename(paths.worktreeDir) || undefined
}

export class GitError extends Error {}

function branchName(gitDir: string): string {
    const head = readText(join(gitDir, 'HEAD'))
    if (head === undefined) {
        throw new GitError(`Failed to determine current branch: failed to open HEAD file at ${join(gitDir, 'HEAD')}`)
    }
    if (head.startsWith('ref: refs/heads/')) {
        return head.replace(/^(ref: refs\/heads\/)+/, '').trim()
    }
    const trimmed = head.trim()
    if (trimmed.length === 40 || trimmed.length === 64) {
        return 'HEAD-detached'
    }
    throw new GitError('Failed to determine current branch: unrecognized HEAD format')
}

function commitSha(paths: RepositoryPaths, branch: string): string {
    if (branch === 'HEAD-detached') {
        return (readText(join(paths.gitDir, 'HEAD')) ?? '').trim()
    }
    const loose = [join(paths.gitDir, 'refs/heads', branch)]
    if (paths.commonDir !== paths.gitDir) {
        loose.push(join(paths.commonDir, 'refs/heads', branch))
    }
    for (const path of loose) {
        if (existsSync(path)) {
            const sha = readText(path)
            if (sha === undefined) {
                throw new GitError(`Failed to determine commit sha: failed to read branch reference at ${path}`)
            }
            return sha.trim()
        }
    }
    // Clones and `git gc` pack loose refs into packed-refs.
    const packed = [join(paths.gitDir, 'packed-refs')]
    if (paths.commonDir !== paths.gitDir) {
        packed.push(join(paths.commonDir, 'packed-refs'))
    }
    const refName = `refs/heads/${branch}`
    for (const path of packed) {
        for (const rawLine of (readText(path) ?? '').split('\n')) {
            const line = rawLine.trim()
            if (!line || line.startsWith('#') || line.startsWith('^')) {
                continue
            }
            const [sha, ref] = line.split(/\s+/)
            if (sha && ref === refName) {
                return sha
            }
        }
    }
    throw new GitError('Failed to determine commit sha: could not determine commit ID')
}

// Git info from CI variables (GitHub Actions, Vercel), else from the repository that contains
// `start`. Undefined when there is neither. Throws a GitError when the repository can't be read.
export function gitInfo(env: Env, start: string): GitInfo | undefined {
    const fromEnv = fromGitHub(env) ?? fromVercel(env)
    if (fromEnv) {
        return fromEnv
    }
    const paths = findRepository(start)
    if (!paths) {
        return undefined
    }
    const info: GitInfo = { branch: '', commit_id: '' }
    const remote = remoteUrl(paths)
    if (remote !== undefined) {
        info.remote_url = remote
    }
    const name = repoName(paths)
    if (name !== undefined) {
        info.repo_name = name
    }
    info.branch = branchName(paths.gitDir)
    info.commit_id = commitSha(paths, info.branch)
    return info
}

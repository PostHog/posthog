import { ErrorTrackingRelease, ErrorTrackingStackFrame } from '../types'
import type { SourceData } from './framesCodeSourceLogic'

export interface RepoRemote {
    host: string
    webOrigin: string
    path: string
}

const URL_SCHEMES = ['https://', 'http://', 'ssh://']
const SCP_REMOTE = /^[^@/:]+@([^@/:]+):(.+)$/
const HOST = /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/
const SEGMENT = /^[A-Za-z0-9._~+-]+$/

/**
 * Parse a git remote URL with the rules ingestion uses to name the repository's file list
 * (`rust/cymbal/src/core/repo_slug.rs`), so a link points at the repository its repo paths came from.
 */
export function parseRepoRemote(remoteUrl: string): RepoRemote | null {
    const url = remoteUrl.trim()
    if (!url || /[\s?#]/.test(url)) {
        return null
    }

    let host: string
    let path: string
    let webOrigin: string | null = null
    const scheme = URL_SCHEMES.find((prefix) => url.toLowerCase().startsWith(prefix))
    if (scheme) {
        const rest = url.slice(scheme.length)
        const slash = rest.indexOf('/')
        if (slash === -1) {
            return null
        }
        const authority = rest.slice(0, slash)
        const [hostName, port] = authority.slice(authority.lastIndexOf('@') + 1).split(':')
        host = hostName.toLowerCase()
        path = rest.slice(slash + 1)
        // An ssh port is not a web port, so only an http(s) remote keeps its port and scheme.
        if (scheme !== 'ssh://') {
            webOrigin = `${scheme}${host}${port ? `:${port}` : ''}`
        }
    } else {
        const match = SCP_REMOTE.exec(url)
        if (!match) {
            return null
        }
        host = match[1].toLowerCase()
        path = match[2]
    }

    path = path
        .replace(/\/+$/, '')
        .replace(/\.git$/, '')
        .replace(/^\//, '')
    const segments = path.split('/')
    const validPath =
        segments.length >= 2 &&
        segments.every((segment) => segment !== '.' && segment !== '..' && SEGMENT.test(segment))
    if (!HOST.test(host) || !validPath) {
        return null
    }
    return { host, webOrigin: webOrigin ?? `https://${host}`, path }
}

/** A direct link to the frame's file and line at the release commit, when ingestion matched the frame to a file. */
export function getRepoFileLink(
    frame: Pick<ErrorTrackingStackFrame, 'repo_path' | 'line'>,
    release: ErrorTrackingRelease | null | undefined
): SourceData | null {
    const git = release?.metadata?.git
    if (!frame.repo_path || !git?.remote_url || !git.commit_id) {
        return null
    }
    const remote = parseRepoRemote(git.remote_url)
    if (!remote) {
        return null
    }

    const filePath = frame.repo_path.split('/').map(encodeURIComponent).join('/')
    const commit = encodeURIComponent(git.commit_id)
    const anchor = frame.line ? `#L${frame.line}` : ''
    if (remote.host === 'github.com') {
        return { provider: 'github', url: `https://github.com/${remote.path}/blob/${commit}/${filePath}${anchor}` }
    }
    // Ingestion lists repository files only through a GitHub or GitLab integration, so any other host is GitLab.
    return { provider: 'gitlab', url: `${remote.webOrigin}/${remote.path}/-/blob/${commit}/${filePath}${anchor}` }
}

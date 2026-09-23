export type GitProvider = 'github' | 'gitlab' | 'bitbucket' | 'unknown'
export const supportedProviders = ['github', 'gitlab']

export type ParsedRemoteUrl = {
    provider: GitProvider
    owner: string
    repository: string
    providerUrl: string | undefined
}

// Keeps the slashes of a path or of a branch like `feature/x`, and escapes the other characters a URL reserves.
function encodePathSegments(value: string): string {
    return value.split('/').map(encodeURIComponent).join('/')
}

export class GitMetadataParser {
    static getCommitLink(remote_url?: string, commit_id?: string): string | undefined {
        if (!commit_id || !remote_url) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildCommitLink(parsedRemoteUrl, commit_id)
    }

    static getBranchLink(remote_url?: string, branch?: string): string | undefined {
        if (!remote_url || !branch) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildBranchLink(parsedRemoteUrl, branch)
    }

    /** Links a sha to its commit and anything else, such as a branch or a tag, to its tree. */
    static getRefLink(remote_url?: string, ref?: string): string | undefined {
        if (!ref) {
            return undefined
        }
        return this.isCommitSha(ref) ? this.getCommitLink(remote_url, ref) : this.getBranchLink(remote_url, ref)
    }

    /** Links a repository-relative file path as it was at a commit, branch or tag. */
    static getFileLink(remote_url?: string, ref?: string, path?: string): string | undefined {
        if (!remote_url || !ref || !path) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildFileLink(parsedRemoteUrl, ref, path)
    }

    /** A full or abbreviated commit sha. A branch named like one reads as a sha too. */
    static isCommitSha(ref: string): boolean {
        return /^[0-9a-f]{7,40}$/i.test(ref)
    }

    static getRepoLink(remote_url?: string): string | undefined {
        if (!remote_url) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildRemoteLink(parsedRemoteUrl)
    }

    static parseRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        return (
            this.parseSshRemoteUrl(remoteUrl) ||
            this.parseHttpsRemoteUrl(remoteUrl) ||
            this.parseSchemelessRemoteUrl(remoteUrl)
        )
    }

    private static buildRemoteLink(parsedUrl: ParsedRemoteUrl): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'gitlab':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}`
            default:
                return undefined
        }
    }

    private static buildBranchLink(parsedUrl: ParsedRemoteUrl, branch: string): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/tree/${branch}`
            case 'gitlab':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/-/tree/${branch}`
            default:
                return undefined
        }
    }

    private static buildCommitLink(parsedUrl: ParsedRemoteUrl, commitSha: string): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/commit/${commitSha}`
            case 'gitlab':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/-/commit/${commitSha}`
            default:
                return undefined
        }
    }

    private static buildFileLink(parsedUrl: ParsedRemoteUrl, ref: string, path: string): string | undefined {
        const encodedRef = encodePathSegments(ref)
        const encodedPath = encodePathSegments(path.replace(/^\.?\//, ''))
        const base = `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}`
        switch (parsedUrl.provider) {
            case 'github':
                return `${base}/blob/${encodedRef}/${encodedPath}`
            case 'gitlab':
                return `${base}/-/blob/${encodedRef}/${encodedPath}`
            case 'bitbucket':
                return `${base}/src/${encodedRef}/${encodedPath}`
            default:
                return undefined
        }
    }

    private static parseSshRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        // git@github.com:user/repo.git

        const atIdx = remoteUrl.indexOf('@')
        const colonIdx = remoteUrl.indexOf(':')
        if (atIdx === -1 || colonIdx === -1) {
            return undefined
        }
        const providerDomain = remoteUrl.slice(atIdx + 1, colonIdx)
        const [provider, providerUrl] = this.parseDomain(providerDomain)
        const afterColon = remoteUrl.slice(colonIdx + 1)
        const slashIdx = afterColon.indexOf('/')

        if (slashIdx === -1) {
            return undefined
        }

        const owner = afterColon.slice(0, slashIdx)
        let repository = afterColon.slice(slashIdx + 1)
        if (repository.endsWith('.git')) {
            repository = repository.slice(0, -4)
        }

        return { provider, owner, repository, providerUrl }
    }

    private static parseHttpsRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        // https://github.com/user/repo.git

        const httpsPrefix = 'https://'
        if (!remoteUrl.startsWith(httpsPrefix)) {
            return undefined
        }

        const withoutProtocol = remoteUrl.slice(httpsPrefix.length)
        const firstSlashIdx = withoutProtocol.indexOf('/')
        if (firstSlashIdx === -1) {
            return undefined
        }

        const domain = withoutProtocol.slice(0, firstSlashIdx)
        const pathParts = withoutProtocol.slice(firstSlashIdx + 1).split('/')

        if (pathParts.length < 2) {
            return undefined
        }

        const owner = pathParts[0]
        let repository = pathParts[1]
        if (repository.endsWith('.git')) {
            repository = repository.slice(0, -4)
        }

        const [provider, providerUrl] = this.parseDomain(domain)

        return { provider, owner, repository, providerUrl }
    }

    private static parseSchemelessRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        // github.com/user/repo, which is how the workflows CLI records a repository
        if (remoteUrl.includes('://') || remoteUrl.includes('@')) {
            return undefined
        }
        return this.parseHttpsRemoteUrl(`https://${remoteUrl}`)
    }

    private static parseDomain(domain: string): [GitProvider, string | undefined] {
        switch (domain) {
            case 'github.com':
                return ['github', 'https://github.com']
            case 'gitlab.com':
                return ['gitlab', 'https://gitlab.com']
            case 'bitbucket.org':
                return ['bitbucket', 'https://bitbucket.org']
            default:
                return ['unknown', `https://${domain}/`]
        }
    }
}

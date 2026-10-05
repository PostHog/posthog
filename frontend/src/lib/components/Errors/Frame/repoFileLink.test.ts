import { ErrorTrackingRelease } from '../types'
import { getRepoFileLink } from './repoFileLink'

const COMMIT = '0123456789abcdef0123456789abcdef01234567'

function release(remoteUrl: string): ErrorTrackingRelease {
    return {
        id: 'release-1',
        version: '1.0.0',
        created_at: '2026-01-01T00:00:00Z',
        metadata: { git: { remote_url: remoteUrl, commit_id: COMMIT } },
    }
}

describe('getRepoFileLink', () => {
    test.each([
        {
            name: 'github https remote',
            remote: 'https://github.com/acme/shop.git',
            repoPath: 'apps/web/src/index.tsx',
            line: 12,
            expected: {
                provider: 'github',
                url: `https://github.com/acme/shop/blob/${COMMIT}/apps/web/src/index.tsx#L12`,
            },
        },
        {
            name: 'github ssh remote',
            remote: 'git@github.com:acme/shop.git',
            repoPath: 'services/api/orders/views.py',
            line: 3,
            expected: {
                provider: 'github',
                url: `https://github.com/acme/shop/blob/${COMMIT}/services/api/orders/views.py#L3`,
            },
        },
        {
            name: 'gitlab nested groups keep the https port',
            remote: 'https://gitlab.example.com:8443/group/sub/project.git',
            repoPath: 'lib/main.dart',
            line: 7,
            expected: {
                provider: 'gitlab',
                url: `https://gitlab.example.com:8443/group/sub/project/-/blob/${COMMIT}/lib/main.dart#L7`,
            },
        },
        {
            name: 'gitlab ssh remote drops the ssh port',
            remote: 'ssh://git@gitlab.example.com:2222/group/project.git',
            repoPath: 'app/models/order.rb',
            line: null,
            expected: {
                provider: 'gitlab',
                url: `https://gitlab.example.com/group/project/-/blob/${COMMIT}/app/models/order.rb`,
            },
        },
        {
            name: 'path segments are encoded',
            remote: 'https://github.com/acme/shop',
            repoPath: 'docs/a file#1.md',
            line: 1,
            expected: {
                provider: 'github',
                url: `https://github.com/acme/shop/blob/${COMMIT}/docs/a%20file%231.md#L1`,
            },
        },
    ])('$name', ({ remote, repoPath, line, expected }) => {
        expect(getRepoFileLink({ repo_path: repoPath, line }, release(remote))).toEqual(expected)
    })

    test.each([
        { name: 'no repo path', repoPath: null, remote: 'https://github.com/acme/shop.git' },
        { name: 'local remote', repoPath: 'src/index.ts', remote: 'file:///srv/git/shop.git' },
        { name: 'remote without a repository', repoPath: 'src/index.ts', remote: 'https://github.com/acme' },
    ])('gives no link for $name', ({ repoPath, remote }) => {
        expect(getRepoFileLink({ repo_path: repoPath, line: 1 }, release(remote))).toBeNull()
    })
})

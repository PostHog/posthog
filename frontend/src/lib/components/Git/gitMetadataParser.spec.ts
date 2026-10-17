import { GitMetadataParser } from './gitMetadataParser'

describe('GitMetadataParser', () => {
    describe('getCommitLink', () => {
        it.each([
            {
                description: 'should create commit link from SSH URL',
                remote_url: 'git@github.com:user/repo.git',
                expected: 'https://github.com/user/repo/commit/commit-sha',
            },
            {
                description: 'should create commit link from HTTPS URL',
                remote_url: 'https://github.com/user/repo.git',
                expected: 'https://github.com/user/repo/commit/commit-sha',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@gitlab.com:posthog-bot-group/posthog-bot-project.git',
                expected: 'https://gitlab.com/posthog-bot-group/posthog-bot-project/-/commit/commit-sha',
            },
            {
                description: 'should create commit link for bitbucket URL',
                remote_url: 'https://bitbucket.org/user/repo.git',
                expected: 'https://bitbucket.org/user/repo/commits/commit-sha',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'invalid_url',
                expected: undefined,
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@otherprovider.com:user/repo.git',
                expected: undefined,
            },
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getCommitLink(remote_url, 'commit-sha')
            expect(result).toBe(expected)
        })
    })

    describe('getBranchLink', () => {
        it.each([
            {
                description: 'should create commit link from SSH URL',
                remote_url: 'git@github.com:user/repo.git',
                expected: 'https://github.com/user/repo/tree/branch-name',
            },
            {
                description: 'should create commit link from HTTPS URL',
                remote_url: 'https://github.com/user/repo.git',
                expected: 'https://github.com/user/repo/tree/branch-name',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@gitlab.com:posthog-bot-group/posthog-bot-project.git',
                expected: 'https://gitlab.com/posthog-bot-group/posthog-bot-project/-/tree/branch-name',
            },
            {
                description: 'should create branch link for bitbucket URL',
                remote_url: 'https://bitbucket.org/user/repo.git',
                expected: 'https://bitbucket.org/user/repo/src/branch-name',
            },
            {
                description: 'should create branch link for a gitlab project in a subgroup',
                remote_url: 'gitlab.com/group/subgroup/project',
                expected: 'https://gitlab.com/group/subgroup/project/-/tree/branch-name',
            },
            {
                description: 'should create branch link for a gitlab remote with a trailing slash',
                remote_url: 'https://gitlab.com/group/project/',
                expected: 'https://gitlab.com/group/project/-/tree/branch-name',
            },
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getBranchLink(remote_url, 'branch-name')
            expect(result).toBe(expected)
        })
    })

    describe('getGitHubRepositorySlug', () => {
        it.each([
            {
                description: 'SSH GitHub remote',
                remote_url: 'git@github.com:PostHog/posthog.git',
                expected: 'PostHog/posthog',
            },
            {
                description: 'HTTPS GitHub remote',
                remote_url: 'https://github.com/PostHog/posthog.git',
                expected: 'PostHog/posthog',
            },
            { description: 'GitLab remote', remote_url: 'git@gitlab.com:group/project.git', expected: undefined },
            {
                description: 'remote with a credential',
                remote_url: 'https://x-access-token:ghs_example@github.com/PostHog/posthog.git',
                expected: undefined,
            },
            { description: 'missing remote', remote_url: undefined, expected: undefined },
        ])('returns the slug for a $description', ({ remote_url, expected }) => {
            expect(GitMetadataParser.getGitHubRepositorySlug(remote_url)).toBe(expected)
        })
    })

    describe('getFileLink', () => {
        it.each([
            {
                description: 'a GitHub remote without a scheme',
                remote_url: 'github.com/example/app',
                expected: 'https://github.com/example/app/blob/main/emails/welcome.html',
            },
            {
                description: 'a GitLab SSH remote',
                remote_url: 'git@gitlab.com:example/app.git',
                expected: 'https://gitlab.com/example/app/-/blob/main/emails/welcome.html',
            },
            {
                description: 'a Bitbucket HTTPS remote',
                remote_url: 'https://bitbucket.org/example/app',
                expected: 'https://bitbucket.org/example/app/src/main/emails/welcome.html',
            },
            { description: 'an unknown host', remote_url: 'git.example.com/example/app', expected: undefined },
        ])('links the file for $description', ({ remote_url, expected }) => {
            expect(GitMetadataParser.getFileLink(remote_url, 'main', './emails/welcome.html')).toBe(expected)
        })

        it('encodes each part of the ref and the path', () => {
            expect(GitMetadataParser.getFileLink('github.com/example/app', 'feat/a b', 'emails/a#b.html')).toBe(
                'https://github.com/example/app/blob/feat/a%20b/emails/a%23b.html'
            )
            expect(GitMetadataParser.getRefLink('github.com/example/app', 'fix#12')).toBe(
                'https://github.com/example/app/tree/fix%2312'
            )
        })
    })
})

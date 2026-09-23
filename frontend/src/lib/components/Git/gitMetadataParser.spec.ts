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
                description: 'should create commit link for gitlab URL',
                remote_url: 'invalid_url',
                expected: undefined,
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@otherprovider.com:user/repo.git',
                expected: undefined,
            },
            {
                description: 'should create commit link from a repository without a scheme',
                remote_url: 'github.com/user/repo',
                expected: 'https://github.com/user/repo/commit/commit-sha',
            },
            {
                description: 'should create commit link from a gitlab repository without a scheme',
                remote_url: 'gitlab.com/group/project',
                expected: 'https://gitlab.com/group/project/-/commit/commit-sha',
            },
            {
                description: 'should not link a repository without a scheme on an unknown host',
                remote_url: 'git.example.com/team/flows',
                expected: undefined,
            },
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getCommitLink(remote_url, 'commit-sha')
            expect(result).toBe(expected)
        })
    })

    describe('getRefLink', () => {
        it.each([
            {
                description: 'links a full sha to its commit',
                remote_url: 'github.com/user/repo',
                ref: '9f2c1ab3d4e5f60718293a4b5c6d7e8f90a1b2c3',
                expected: 'https://github.com/user/repo/commit/9f2c1ab3d4e5f60718293a4b5c6d7e8f90a1b2c3',
            },
            {
                description: 'links a short sha to its commit on gitlab',
                remote_url: 'gitlab.com/group/project',
                ref: '9f2c1ab',
                expected: 'https://gitlab.com/group/project/-/commit/9f2c1ab',
            },
            {
                description: 'links a branch to its tree',
                remote_url: 'github.com/user/repo',
                ref: 'main',
                expected: 'https://github.com/user/repo/tree/main',
            },
            {
                description: 'links nothing without a ref',
                remote_url: 'github.com/user/repo',
                ref: undefined,
                expected: undefined,
            },
        ])('$description', ({ remote_url, ref, expected }) => {
            expect(GitMetadataParser.getRefLink(remote_url, ref)).toBe(expected)
        })
    })

    describe('getFileLink', () => {
        it.each([
            {
                description: 'links a file at a sha on github',
                remote_url: 'github.com/user/repo',
                ref: '9f2c1ab',
                path: 'workflows/welcome.ts',
                expected: 'https://github.com/user/repo/blob/9f2c1ab/workflows/welcome.ts',
            },
            {
                description: 'links a file at a branch with a slash on gitlab',
                remote_url: 'git@gitlab.com:group/project.git',
                ref: 'feature/flows',
                path: 'workflows/welcome.ts',
                expected: 'https://gitlab.com/group/project/-/blob/feature/flows/workflows/welcome.ts',
            },
            {
                description: 'drops a leading ./ and escapes reserved characters in the path',
                remote_url: 'https://github.com/user/repo.git',
                ref: 'main',
                path: './workflows/my welcome#1.ts',
                expected: 'https://github.com/user/repo/blob/main/workflows/my%20welcome%231.ts',
            },
            {
                description: 'links nothing on an unknown host',
                remote_url: 'git.example.com/team/flows',
                ref: 'main',
                path: 'workflows/welcome.ts',
                expected: undefined,
            },
            {
                description: 'links nothing without a ref',
                remote_url: 'github.com/user/repo',
                ref: undefined,
                path: 'workflows/welcome.ts',
                expected: undefined,
            },
        ])('$description', ({ remote_url, ref, path, expected }) => {
            expect(GitMetadataParser.getFileLink(remote_url, ref, path)).toBe(expected)
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
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getBranchLink(remote_url, 'branch-name')
            expect(result).toBe(expected)
        })
    })
})

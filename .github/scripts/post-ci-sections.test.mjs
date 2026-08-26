import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildDocsPreviewSection } from './post-docs-preview-section.mjs'
import { buildHobbySection } from './post-hobby-section.mjs'
import { buildTrunkLaneSection, postTrunkLaneSection } from './post-trunk-lane-section.mjs'

const commonHobby = {
    previewMode: true,
    sha: '1234567890abcdef',
    runNumber: '42',
    runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
}

describe('CI report section builders', () => {
    for (const testCase of [
        {
            name: 'does not post a stale lane assignment',
            expectedHeadSha: 'old-sha',
            currentHeadSha: 'new-sha',
            expectedPosts: 0,
        },
        {
            name: 'posts the current lane assignment',
            expectedHeadSha: 'current-sha',
            currentHeadSha: 'current-sha',
            expectedPosts: 1,
        },
    ]) {
        it(testCase.name, async () => {
            const postedSections = []
            await postTrunkLaneSection({
                impactedTargets: ['fe:core'],
                isUniversal: false,
                expectedHeadSha: testCase.expectedHeadSha,
                getCurrentHeadSha: async () => testCase.currentHeadSha,
                post: async (section) => postedSections.push(section),
            })
            assert.equal(postedSections.length, testCase.expectedPosts)
        })
    }

    for (const testCase of [
        {
            name: 'describes the universal lane',
            input: { impactedTargets: ['py:core', 'fe:core'], isUniversal: true },
            expected: {
                status: 'alert',
                summary: 'universal lane',
                body: 'This PR is assigned to the universal lane. It cannot merge in parallel with other PRs, so it can take longer to merge. Ask dev-ex if you think this is wrong.',
            },
        },
        {
            name: 'describes the backend Python lane',
            input: { impactedTargets: ['py:product:surveys', 'fe:product:<script>'], isUniversal: false },
            expected: {
                status: 'warn',
                summary: 'backend Python lane',
                body: 'This PR is assigned to the backend Python lane. It runs backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
        {
            name: 'describes a non-backend lane',
            input: { impactedTargets: ['fe:core'], isUniversal: false },
            expected: {
                status: 'ok',
                summary: 'non-backend lane',
                body: 'This PR is assigned to the non-backend lane. It does not run backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
    ]) {
        it(testCase.name, () => {
            assert.deepEqual(buildTrunkLaneSection(testCase.input), testCase.expected)
        })
    }

    it('renders a docs preview link after a successful trigger', () => {
        const section = buildDocsPreviewSection({
            triggerStatus: 'success',
            deploymentUrl: 'https://preview.example.com',
            deploymentId: 'deployment-123',
            runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
            now: new Date('2026-07-14T10:00:00Z'),
        })
        assert.equal(section.status, 'info')
        assert.match(section.body, /https:\/\/preview\.example\.com/)
        assert.match(section.body, /Jul 14, 2026/)
    })

    it('links to workflow logs when the docs preview trigger fails', () => {
        const section = buildDocsPreviewSection({
            triggerStatus: 'failure',
            runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
        })
        assert.equal(section.status, 'fail')
        assert.match(section.body, /actions\/runs\/42/)
    })

    it('moves a hobby preview through setup, ready, and failed states', () => {
        const initial = buildHobbySection({ state: 'initial', ...commonHobby })
        const ready = buildHobbySection({
            state: 'final',
            ...commonHobby,
            files: {
                testExitCode: '0',
                dropletInfo: 'URL: https://hobby.example.com\nSSH: ssh root@example.com\nDroplet IP: 127.0.0.1\n',
                output: 'created',
            },
        })
        const failed = buildHobbySection({
            state: 'final',
            ...commonHobby,
            files: {
                testExitCode: '1',
                dropletInfo: 'URL: https://hobby.example.com\n',
                cloudInitLogs: 'line 1\nline 2',
                output: 'created',
            },
        })

        assert.equal(initial.status, 'info')
        assert.equal(ready.status, 'ok')
        assert.match(ready.body, /https:\/\/hobby\.example\.com/)
        assert.equal(failed.status, 'fail')
        assert.match(failed.body, /line 2/)
    })
})

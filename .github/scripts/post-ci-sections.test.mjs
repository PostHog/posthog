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
            name: 'marks the universal lane red',
            input: { impactedTargets: ['py:core', 'fe:core'], isUniversal: true },
            expectedStatus: 'fail',
        },
        {
            name: 'marks a backend Python lane yellow',
            input: { impactedTargets: ['py:product:surveys'], isUniversal: false },
            expectedStatus: 'warn',
        },
        {
            name: 'marks other lanes green',
            input: { impactedTargets: ['fe:core'], isUniversal: false },
            expectedStatus: 'ok',
        },
    ]) {
        it(testCase.name, () => {
            assert.equal(buildTrunkLaneSection(testCase.input).status, testCase.expectedStatus)
        })
    }

    it('renders a direct link per changed docs page after a successful trigger', () => {
        const section = buildDocsPreviewSection({
            triggerStatus: 'success',
            deploymentUrl: 'https://preview.example.com',
            deploymentId: 'deployment-123',
            runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
            changedPaths: [
                'docs/published/docs/data/test-accounts.mdx',
                'docs/published/handbook/engineering/developing-locally.md',
                'docs/published/docs/images/diagram.png',
            ],
            now: new Date('2026-07-14T10:00:00Z'),
        })
        assert.equal(section.status, 'info')
        assert.match(section.body, /Jul 14, 2026/)
        // Each markdown page links to its own preview URL, not the site root.
        assert.match(
            section.body,
            /\[`\/docs\/data\/test-accounts`\]\(https:\/\/preview\.example\.com\/docs\/data\/test-accounts\)/
        )
        assert.match(
            section.body,
            /\[`\/handbook\/engineering\/developing-locally`\]\(https:\/\/preview\.example\.com\/handbook\/engineering\/developing-locally\)/
        )
        // Non-page assets are not listed, and the old hardcoded hint is gone.
        assert.doesNotMatch(section.body, /diagram\.png/)
        assert.doesNotMatch(section.body, /Open the preview at/)
    })

    it('caps the docs page list on a large PR', () => {
        const changedPaths = Array.from({ length: 30 }, (_, i) => `docs/published/docs/page-${i}.md`)
        const section = buildDocsPreviewSection({
            triggerStatus: 'success',
            deploymentUrl: 'https://preview.example.com',
            deploymentId: 'deployment-123',
            runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
            changedPaths,
            now: new Date('2026-07-14T10:00:00Z'),
        })
        assert.match(section.body, /…and 5 more changed pages\./)
    })

    it('falls back to the preview root when no docs pages changed', () => {
        const section = buildDocsPreviewSection({
            triggerStatus: 'success',
            deploymentUrl: 'https://preview.example.com',
            deploymentId: 'deployment-123',
            runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
            now: new Date('2026-07-14T10:00:00Z'),
        })
        assert.equal(section.status, 'info')
        assert.match(section.body, /\[Open preview\]\(https:\/\/preview\.example\.com\)/)
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

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, it } from 'node:test'

import { buildDependencyScanSection } from './post-dependency-scan-section.mjs'
import { buildDocsPreviewSection } from './post-docs-preview-section.mjs'
import { buildHobbySection } from './post-hobby-section.mjs'
import { buildHogboxPreviewSection } from './post-hogbox-preview-section.mjs'
import {
    buildQuarantinedFailuresSection,
    collectFailures,
    failedTestIds,
    testJobsPassed,
} from './post-quarantined-failures-section.mjs'
import { buildTrunkLaneSection, parseCrossLane, postTrunkLaneSection } from './post-trunk-lane-section.mjs'

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
            input: { impactedTargets: ['fe:core', 'node:ingestion'], isUniversal: false },
            expected: {
                status: 'ok',
                summary: 'non-backend lane',
                body: 'This PR is assigned to the non-backend lane. It does not run backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
        {
            name: 'names the single non-backend target',
            input: { impactedTargets: ['fe:product:desktop'], isUniversal: false },
            expected: {
                status: 'ok',
                summary: 'non-backend lane (<code>fe:product:desktop</code>)',
                body: 'This PR is assigned to the non-backend lane (<code>fe:product:desktop</code>). It does not run backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
        {
            name: 'names the single backend Python target',
            input: { impactedTargets: ['py:product:surveys'], isUniversal: false },
            expected: {
                status: 'warn',
                summary: 'backend Python lane (<code>py:product:surveys</code>)',
                body: 'This PR is assigned to the backend Python lane (<code>py:product:surveys</code>). It runs backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
        {
            name: 'escapes a target before rendering it',
            input: { impactedTargets: ['</summary><img src="x">'], isUniversal: false },
            expected: {
                status: 'ok',
                summary: 'non-backend lane (<code>&lt;/summary&gt;&lt;img src=&quot;x&quot;&gt;</code>)',
                body: 'This PR is assigned to the non-backend lane (<code>&lt;/summary&gt;&lt;img src=&quot;x&quot;&gt;</code>). It does not run backend Python tests and may merge in parallel with PRs in other lanes.',
            },
        },
    ]) {
        it(testCase.name, () => {
            assert.deepEqual(buildTrunkLaneSection(testCase.input), testCase.expected)
        })
    }

    it('warns and names both sides when a PR mixes lanes', () => {
        const section = buildTrunkLaneSection({
            impactedTargets: ['node:ingestion', 'py:core'],
            isUniversal: false,
            crossLane: { mixed: true, heavyFiles: ['posthog/api/x.py'], lightFiles: ['nodejs/src/y.ts'] },
        })
        assert.equal(section.status, 'warn')
        assert.match(section.summary, /mixes lanes/)
        assert.match(section.body, /<code>posthog\/api\/x\.py<\/code>/)
        assert.match(section.body, /<code>nodejs\/src\/y\.ts<\/code>/)
    })

    it('counts the files the telemetry cut from a capped list', () => {
        const crossLane = parseCrossLane({
            cross_lane: true,
            cross_lane_heavy_files: ['a.py', 'b.py', 'c.py', 'd.py'],
            cross_lane_heavy_file_count: 150,
            cross_lane_light_files: ['nodejs/src/y.ts'],
        })
        const section = buildTrunkLaneSection({ impactedTargets: ['node:ingestion', 'py:core'], crossLane })
        assert.match(section.body, /<code>c\.py<\/code> and 147 more/)
    })

    it('gives no cross-lane warning when the file lists have the wrong shape', () => {
        assert.equal(
            parseCrossLane({ cross_lane: true, cross_lane_heavy_files: 'a.py', cross_lane_light_files: [1] }),
            null
        )
    })

    for (const testCase of [
        {
            name: 'reports a clean dependency scan',
            input: {
                scanned: 4,
                skipped: 0,
                flagged: [{ ecosystem: 'pypi', package: 'idna@3.10', label: 'low', score: 4.9, rules: [] }],
            },
            status: 'ok',
            summary: 'clean, 4 packages scanned',
        },
        {
            name: 'warns on a high-risk package',
            input: {
                scanned: 2,
                skipped: 0,
                flagged: [
                    { ecosystem: 'npm', package: 'left-pad@1.3.1', label: 'high_risk', score: 8.8, rules: ['a|b'] },
                ],
            },
            status: 'warn',
            summary: '1 high-risk package',
        },
        {
            name: 'warns on packages the scanner could not read',
            input: {
                scanned: 1,
                skipped: 2,
                flagged: [
                    { ecosystem: 'go', package: 'example.com/m@v1.0.0', label: 'not_scanned', score: 0, rules: [] },
                ],
            },
            status: 'warn',
            summary: '3 packages not scanned',
        },
    ]) {
        it(testCase.name, () => {
            const section = buildDependencyScanSection(testCase.input)
            assert.equal(section.status, testCase.status)
            assert.equal(section.summary, testCase.summary)
            assert.doesNotMatch(section.body.split('\n').at(-1), /a\|b/)
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

    for (const testCase of [
        {
            name: 'claims the PR frontend only when it was swapped in',
            frontendSwapped: true,
            expected: /\*\*and\*\* frontend/,
        },
        {
            name: 'says the frontend is unchanged when it was not swapped in',
            frontendSwapped: false,
            expected: /frontend unchanged by this PR/,
        },
    ]) {
        it(testCase.name, () => {
            const section = buildHogboxPreviewSection({
                state: 'ready',
                sha: '1234567890abcdef',
                runUrl: 'https://github.com/PostHog/posthog/actions/runs/42',
                url: 'https://preview.example.com',
                boxId: 'box-1',
                penId: 'None',
                consoleHost: 'console.example.com',
                frontendSwapped: testCase.frontendSwapped,
            })
            assert.equal(section.status, 'ok')
            assert.match(section.summary, /https:\/\/preview\.example\.com/)
            assert.match(section.body, testCase.expected)
            assert.doesNotMatch(section.body, /console\/fleet\/pens/)
        })
    }

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

describe('quarantined failures section', () => {
    const report = `<?xml version="1.0"?><testsuites><testsuite name="pytest">
        <testcase classname="posthog.api.test.test_a.TestA" name="test_passes" file="posthog/api/test/test_a.py"/>
        <testcase classname="posthog.api.test.test_a.TestA" name="test_fails" file="posthog/api/test/test_a.py"><failure message="assert 400 == 201">boom</failure></testcase>
        <testcase classname="posthog.api.test.test_a.TestA" name="test_errors[a&amp;b]" file="posthog/api/test/test_a.py"><error message="setup">boom</error></testcase>
        <testcase classname="posthog.api.test.test_a.TestA" name="test_shared" file="posthog/api/test/test_a.py"><failure message="inherited">x</failure></testcase>
        <testcase classname="posthog.api.test.test_a.TestB" name="test_shared" file="posthog/api/test/test_a.py"><failure message="other class">x</failure></testcase>
        <testcase classname="posthog.api.test.test_a.TestA" name="test_skipped" file="posthog/api/test/test_a.py"><skipped message="s"/></testcase>
    </testsuite></testsuites>`

    it('lists each failing test with its class, even when another class has a test with the same name', () => {
        assert.deepEqual(failedTestIds(report), [
            'posthog/api/test/test_a.py::TestA::test_fails',
            'posthog/api/test/test_a.py::TestA::test_errors[a&b]',
            'posthog/api/test/test_a.py::TestA::test_shared',
            'posthog/api/test/test_a.py::TestB::test_shared',
        ])
    })

    it('refuses a report that declares entities', () => {
        assert.deepEqual(failedTestIds(`<!DOCTYPE x [<!ENTITY a "b">]>${report}`), [])
    })

    it('reads shard and product reports from artifact directories', () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'junit-'))
        fs.mkdirSync(path.join(dir, 'junit-results-backend-core-4'))
        fs.writeFileSync(path.join(dir, 'junit-results-backend-core-4', 'junit-core.xml'), report)
        for (const shard of ['0', '1']) {
            fs.mkdirSync(path.join(dir, `product-junit-results-${shard}`))
            fs.writeFileSync(path.join(dir, `product-junit-results-${shard}`, 'junit-product-surveys.xml'), report)
        }
        const shards = new Set(collectFailures(dir).map((failure) => failure.shard))
        assert.deepEqual([...shards].sort(), ['core-4', 'products-0', 'products-1'])
        assert.equal(collectFailures(dir).filter((failure) => failure.shard === 'core-4').length, 4)
        assert.equal(collectFailures(path.join(dir, 'missing')), null)
        assert.equal(collectFailures(fs.mkdtempSync(path.join(os.tmpdir(), 'junit-empty-'))), null)
    })

    it('warns with the count of failures and shards', () => {
        const section = buildQuarantinedFailuresSection([
            { shard: 'core-4', test: 'a.py::one' },
            { shard: 'core-4', test: 'a.py::two' },
            { shard: 'core-5', test: 'b.py::three' },
        ])
        assert.equal(section.status, 'warn')
        assert.equal(section.summary, '3 quarantined failures in 2 shards')
        assert.match(section.body, /\| core-5 \| `b\.py::three` \|/)
    })

    it('trusts the failures only when no test job failed or was cancelled', () => {
        assert.equal(testJobsPassed(['success', 'skipped']), true)
        assert.equal(testJobsPassed(['success', 'failure']), false)
        assert.equal(testJobsPassed(['cancelled', 'success']), false)
        assert.equal(testJobsPassed([undefined, 'success']), false)
    })
})

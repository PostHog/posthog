import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    buildBlocks,
    buildEditorCell,
    buildEditorIndex,
    buildEditors,
    fetchSlowTests,
    formatDurationSeconds,
    rankReportCandidates,
    resolveSlackUsers,
    selectReportCandidates,
    tableRows,
} from './weekly-slow-tests-report.mjs'

const ITEM = {
    runner: 'pytest',
    selector: 'posthog/api/test/test_slow_thing.py::TestSlow::test_it_crawls',
    file: 'posthog/api/test/test_slow_thing.py',
    p50_seconds: 95.2,
    max_seconds: 121.4,
    builds: 18,
    repoPath: 'posthog/api/test/test_slow_thing.py',
}

const onMasterResolver = (path) => [path]

describe('weekly slow tests report', () => {
    it('scopes the span query to passed tests on master-side branches in this repo', async () => {
        const { repoPath: _repoPath, ...expected } = ITEM
        let captured
        const items = await fetchSlowTests(async (query, values) => {
            captured = { query, values }
            return { results: [[ITEM.runner, ITEM.selector, ITEM.file, 95.2, 121.4, 18]] }
        })

        assert.deepEqual(items, [expected])

        assert.match(captured.query, /attributes\['test\.outcome'\] = 'passed'/)
        assert.match(captured.query, /lower\(resource_attributes\['ci\.repository'\]\) = lower\(\{repository\}\)/)
        assert.match(captured.query, /ci\.branch'\] = {for_branch} OR resource_attributes\['ci\.branch'\] LIKE {merge_queue_glob}/)
        assert.match(captured.query, /GROUP BY/)
        assert.equal(captured.values.repository, 'PostHog/posthog')
        assert.equal(captured.values.for_branch, 'master')
        assert.equal(captured.values.merge_queue_glob, 'trunk-merge/%')
        assert.equal(captured.values.min_builds, 3)
    })

    it('keeps only tests whose file exists in the master checkout and caps the pool', () => {
        const items = Array.from({ length: 35 }, (_, index) => ({
            ...ITEM,
            selector: `file_${index}.py::test_${index}`,
            file: `file_${index}.py`,
            p50_seconds: 100 - index,
        }))
        items[34] = { ...items[34], file: 'products/new/backend/test_unmerged.py', selector: 'x.py::test_x' }
        const toRepoPaths = (path) => (path === 'products/new/backend/test_unmerged.py' ? [] : [path])

        const kept = selectReportCandidates(items, toRepoPaths)

        assert.equal(kept.length, 30)
        assert.ok(kept.every((item) => item.file !== 'products/new/backend/test_unmerged.py'))
        assert.deepEqual(kept[0].repoPaths, [items[0].file])
    })

    it('ranks by median duration, breaking ties on the max', () => {
        const items = [
            { ...ITEM, selector: 'a.py::test_a', p50_seconds: 40, max_seconds: 999 },
            { ...ITEM, selector: 'b.py::test_b', p50_seconds: 60, max_seconds: 61 },
            { ...ITEM, selector: 'c.py::test_c', p50_seconds: 40, max_seconds: 41 },
        ]

        assert.deepEqual(
            rankReportCandidates(items, 10).map((item) => item.selector),
            ['b.py::test_b', 'a.py::test_a', 'c.py::test_c']
        )
        assert.deepEqual(rankReportCandidates(items, 2).map((item) => item.selector), ['b.py::test_b', 'a.py::test_a'])
    })

    it('dedupes editors newest-first, skips bots, and caps at two', () => {
        const commits = [
            { sha: '1', commit: { author: { email: 'ada@example.com' } }, author: { login: 'adalovelace' } },
            { sha: '2', commit: { author: { email: 'dep@example.com' } }, author: { login: 'dependabot[bot]' } },
            { sha: '3', commit: { author: { email: 'ada@example.com' } }, author: { login: 'adalovelace' } },
            { sha: '4', commit: { author: { email: 'grace@example.com' } }, author: { login: 'ghopper' } },
            { sha: '5', commit: { author: { email: 'alan@example.com' } }, author: { login: 'aturing' } },
            { sha: '6', commit: { author: { email: 'ghost@example.com' } }, author: null },
        ]

        assert.deepEqual(buildEditors(commits), [
            { login: 'adalovelace', email: 'ada@example.com' },
            { login: 'ghopper', email: 'grace@example.com' },
        ])
        assert.deepEqual(buildEditors([]), [])
    })

    it('resolves Slack ids by the login field first, then by email, else keeps the GitHub mention', async () => {
        const calls = []
        const slackFetch = async (url) => {
            calls.push(url)
            if (url.startsWith('users.list')) {
                return {
                    ok: true,
                    members: [
                        { id: 'U1', profile: { login: 'adalovelace' } },
                        { id: 'U3', name: 'aturing' },
                    ],
                }
            }
            if (url.startsWith('users.lookupByEmail')) {
                const email = new URL(`https://slack.com/api/${url}`).searchParams.get('email')
                return email === 'grace@example.com'
                    ? { ok: true, user: { id: 'U2' } }
                    : { ok: false, error: 'users_not_found' }
            }
            return assert.fail(`unexpected Slack call: ${url}`)
        }

        const resolved = await resolveSlackUsers(
            [
                { login: 'adalovelace', email: 'ada@example.com' },
                { login: 'ghopper', email: 'grace@example.com' },
                { login: 'aturing', email: 'alan@example.com' },
            ],
            slackFetch
        )

        assert.deepEqual(resolved, [
            { login: 'adalovelace', email: 'ada@example.com', slackId: 'U1' },
            { login: 'ghopper', email: 'grace@example.com', slackId: 'U2' },
            { login: 'aturing', email: 'alan@example.com', slackId: 'U3' },
        ])
        assert.deepEqual(
            calls,
            ['users.list', 'users.lookupByEmail?email=grace%40example.com'],
            'the member directory is fetched once for everyone; email lookup only fires for users it missed'
        )
    })

    it('renders resolved users as Slack mentions and the rest as GitHub links', () => {
        const cell = buildEditorCell([
            { login: 'adalovelace', email: 'ada@example.com', slackId: 'U1' },
            { login: 'aturing', email: 'alan@example.com', slackId: null },
        ])

        assert.deepEqual(cell, {
            type: 'rich_text',
            elements: [
                {
                    type: 'rich_text_section',
                    elements: [
                        { type: 'user', user_id: 'U1' },
                        { type: 'text', text: ', ' },
                        { type: 'link', url: 'https://github.com/aturing', text: '@aturing' },
                    ],
                },
            ],
        })
        assert.deepEqual(buildEditorCell([]), { type: 'raw_text', text: 'unknown' })
    })

    it('queries each file once and caches the login directory across files', async () => {
        const candidates = [
            { ...ITEM, file: 'a.py', repoPaths: ['a.py'] },
            { ...ITEM, selector: 'a.py::test_other', file: 'a.py', repoPaths: ['a.py'] },
            { ...ITEM, file: 'b.py', repoPaths: ['b.py'] },
        ]
        const githubCalls = []
        const editorIndex = await buildEditorIndex(
            candidates,
            async (url) => {
                githubCalls.push(url)
                assert.match(url, /^https:\/\/api\.github\.com\/repos\/PostHog\/posthog\/commits\?/)
                const path = new URL(url).searchParams.get('path')
                return [{ sha: '1', commit: { author: { email: `${path}@example.com` } }, author: { login: `editor-of-${path}` } }]
            }
        )

        assert.equal(githubCalls.length, 2)
        assert.equal(editorIndex.get('a.py').length, 1)
        assert.equal(editorIndex.get('a.py')[0].login, 'editor-of-a.py')
        assert.equal(editorIndex.get('b.py')[0].email, 'b.py@example.com')
    })

    it('reports unknown editors instead of failing when the GitHub lookup errors', async () => {
        const editorIndex = await buildEditorIndex([{ ...ITEM, file: 'a.py', repoPaths: ['a.py'] }], async () => {
            throw new Error('rate limited')
        })

        assert.deepEqual(editorIndex.get('a.py'), [])
    })

    it('formats durations compactly', () => {
        const cases = [
            [45.3, '45s'],
            [89.9, '1m 30s'],
            [121.4, '2m 1s'],
            [59.9, '1m 0s'],
            [3.2, '3s'],
        ]
        for (const [seconds, expected] of cases) {
            assert.equal(formatDurationSeconds(seconds), expected, `${seconds}s`)
        }
    })

    it('builds a six-column Slack table with supported cells and structured links', () => {
        const editorFor = () => [{ login: 'adalovelace', email: 'ada@example.com', slackId: 'U1' }]
        const rows = tableRows(
            [ITEM],
            () => ({ owner: 'team-observability', repoPath: ITEM.file }),
            editorFor
        )
        const blocks = buildBlocks(new Date('2026-08-03T00:00:00Z'), rows)
        const table = blocks.find((block) => block.type === 'table')

        assert.ok(table)
        assert.deepEqual(
            table.rows[0].map((tableCell) => tableCell.text),
            ['test', 'p50', 'max', 'builds', 'owner', 'last edited by']
        )
        for (const tableCell of table.rows.flat()) {
            assert.ok(['raw_text', 'raw_number', 'rich_text'].includes(tableCell.type))
        }
        assert.deepEqual(rows[0][0], {
            type: 'rich_text',
            elements: [
                {
                    type: 'rich_text_section',
                    elements: [
                        {
                            type: 'link',
                            url: 'https://github.com/PostHog/posthog/blob/master/posthog/api/test/test_slow_thing.py',
                            text: 'test_it_crawls',
                        },
                    ],
                },
            ],
        })
        assert.deepEqual(rows[0][1], { type: 'raw_text', text: '1m 35s' })
        assert.deepEqual(rows[0][2], { type: 'raw_text', text: '2m 1s' })
        assert.deepEqual(rows[0][3], { type: 'raw_text', text: '18' })
        assert.deepEqual(rows[0][4], { type: 'raw_text', text: 'observability' })
        assert.deepEqual(
            blocks[0].text.text,
            '*Weekly slow tests - 2026-08-03* _(passing tests on master CI, last 7 days)_'
        )
    })
})

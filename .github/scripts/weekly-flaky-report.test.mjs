import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    buildBlocks,
    buildQueue,
    CLUSTER_MIN_TESTS,
    enrich,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    REPORT_RUNNERS,
    selectReportCandidates,
    tableRows,
} from './weekly-flaky-report.mjs'

describe('weekly flaky report', () => {
    it('builds runner-specific endpoint URLs before the endpoint limit', () => {
        const pytestUrl = flakyTestsUrl('pytest')
        const jestUrl = flakyTestsUrl('jest')

        assert.deepEqual(REPORT_RUNNERS, ['pytest'])
        assert.equal(pytestUrl.searchParams.get('runner'), 'pytest')
        assert.equal(jestUrl.searchParams.get('runner'), 'jest')
        assert.equal(jestUrl.searchParams.get('repo'), 'PostHog/posthog')
        assert.equal(jestUrl.searchParams.get('limit'), '100')
    })

    it('builds a Slack table with supported cells and structured links', () => {
        const rows = tableRows(
            [
                {
                    selector: 'posthog/test/test_example.py::TestExample::test_report',
                    classification: 'confirmed_flake',
                    quarantined_failed_run_count: 0,
                    failed_run_count: 4,
                },
            ],
            () => ({ owner: 'team-devex', repoPath: 'posthog/test/test_example.py' }),
            () => ({
                runsRescued: 2,
                evidence: [
                    { runId: 10, jobId: 20 },
                    { runId: 11, jobId: 21 },
                ],
            })
        )
        const blocks = buildBlocks(new Date('2026-07-27T00:00:00Z'), rows)
        const table = blocks.find((block) => block.type === 'table')

        assert.ok(table)
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
                            url: 'https://github.com/PostHog/posthog/blob/master/posthog/test/test_example.py',
                            text: 'test_report',
                        },
                    ],
                },
            ],
        })
        assert.deepEqual(rows[0][4], {
            type: 'rich_text',
            elements: [
                {
                    type: 'rich_text_section',
                    elements: [
                        {
                            type: 'link',
                            url: 'https://github.com/PostHog/posthog/actions/runs/10/job/20',
                            text: '1',
                        },
                        { type: 'text', text: ' ' },
                        {
                            type: 'link',
                            url: 'https://github.com/PostHog/posthog/actions/runs/11/job/21',
                            text: '2',
                        },
                    ],
                },
            ],
        })
    })

    it('selects proved flakes for the requested runner', () => {
        const common = {
            failed_run_count: 4,
            failed_pr_count: 1,
            master_failed_run_count: 3,
            quarantined_failed_run_count: 0,
        }
        const items = [
            { ...common, runner: 'pytest', selector: 'test_proved.py::test_proved', classification: 'confirmed_flake' },
            {
                ...common,
                runner: 'pytest',
                selector: 'test_burst.py::test_burst',
                classification: 'suspected_regression',
            },
            { ...common, runner: 'jest', selector: 'test_report.ts', classification: 'confirmed_flake' },
        ]

        assert.deepEqual(
            selectReportCandidates(items, 'pytest').map((candidate) => candidate.selector),
            ['test_proved.py::test_proved']
        )
        assert.deepEqual(
            selectReportCandidates(items, 'jest').map((candidate) => candidate.selector),
            ['test_report.ts']
        )
    })

    it('fetches each runner into its own candidate pool', async () => {
        const requestedRunners = []
        const pools = await fetchCandidatePools(['pytest', 'jest'], async (runner) => {
            requestedRunners.push(runner)
            return {
                items: [
                    { runner, selector: `${runner}.test`, classification: 'confirmed_flake' },
                    { runner: runner === 'pytest' ? 'jest' : 'pytest', selector: 'other.test' },
                ],
            }
        })

        assert.deepEqual(requestedRunners, ['pytest', 'jest'])
        assert.deepEqual(
            pools.map(({ runner, candidates }) => [runner, candidates.map((candidate) => candidate.selector)]),
            [
                ['pytest', ['pytest.test']],
                ['jest', ['jest.test']],
            ]
        )
    })

    it('scopes enrichment to the current repository', async () => {
        let request
        await enrich([{ selector: 'products/example/backend/test_report.py::test_report' }], async (query, values) => {
            request = { query, values }
            return { results: [] }
        })

        assert.match(request.query, /lower\(f\.repo\) = lower\(\{repository\}\)/)
        assert.equal(request.values.repository, 'PostHog/posthog')
        assert.deepEqual(request.values.selectors, [
            'products/example/backend/test_report.py::test_report',
            'backend/test_report.py::test_report',
        ])
    })

    it('reports without Trunk state when uploads are off, the table is missing, or it is empty', async () => {
        const item = { selector: 'posthog/test/test_example.py::test_report' }
        const cases = [
            {
                label: 'uploads off',
                enabled: false,
                runHogql: () => assert.fail('must not query Trunk while uploads are disabled'),
            },
            {
                label: 'table missing',
                enabled: true,
                runHogql: async () => {
                    throw new Error('Unknown table trunkio.quarantinedtests')
                },
            },
            { label: 'no rows', enabled: true, runHogql: async () => ({ results: [] }) },
        ]

        for (const { label, enabled, runHogql } of cases) {
            const trunkFor = await fetchTrunkQuarantined('pytest', runHogql, enabled)

            assert.equal(trunkFor(item), null, label)
        }
    })

    it('matches Trunk rows to a product suite reported product-relative', async () => {
        const trunkFor = await fetchTrunkQuarantined(
            'pytest',
            async () => ({
                results: [
                    [
                        'products/example/backend/tests/test_migration.py::MigrationTest::test_backfill',
                        '2026-07-29T09:14:22.000Z',
                    ],
                ],
            }),
            true
        )

        assert.equal(
            trunkFor({ selector: 'backend/tests/test_migration.py::MigrationTest::test_backfill' }).quarantinedAt,
            '2026-07-29T09:14:22.000Z'
        )
        assert.equal(trunkFor({ selector: 'backend/tests/test_migration.py::MigrationTest::test_other' }), null)
    })

    it('parks Trunk-quarantined tests only while masking is on, and labels them otherwise', () => {
        const items = [
            { runner: 'pytest', selector: 'masked.py::test_masked', failed_run_count: 9, failed_pr_count: 9 },
            { runner: 'pytest', selector: 'plain.py::test_plain', failed_run_count: 1, failed_pr_count: 1 },
        ]
        const trunkFor = (item) =>
            item.selector === 'masked.py::test_masked' ? { quarantinedAt: '2026-07-13T17:12:22.000Z' } : null
        const selectors = (list) => list.map((item) => item.selector)

        const masked = buildQueue(items, trunkFor, true)
        const unmasked = buildQueue(items, trunkFor, false)

        assert.deepEqual(selectors(masked.queue), ['plain.py::test_plain'])
        assert.deepEqual(selectors(masked.parked), ['masked.py::test_masked'])
        // Masking off leaves the failure reddening CI, so it stays ranked and carries a label.
        assert.deepEqual(selectors(unmasked.queue), selectors(items))
        assert.deepEqual(unmasked.parked, [])
        const [ownerCell] = tableRows(
            [items[0]],
            () => ({ owner: 'team-devex', repoPath: null }),
            () => ({ runsRescued: null, evidence: [] }),
            trunkFor
        ).map((row) => row[1])
        assert.equal(ownerCell.text, 'devex (Trunk flagged)')
    })

    it('parks a quarantined test that would otherwise be buried in a collapsed cluster', () => {
        // A cluster's selector is a bare file path, so it can never match a Trunk node id.
        const items = Array.from({ length: CLUSTER_MIN_TESTS }, (_, index) => ({
            runner: 'pytest',
            selector: `shared.py::test_${index}`,
            failed_run_count: 2,
            failed_pr_count: 2,
        }))

        const { queue, parked } = buildQueue(items, () => ({ quarantinedAt: '2026-07-13T17:12:22.000Z' }), true)

        assert.deepEqual(queue, [])
        assert.equal(parked.length, CLUSTER_MIN_TESTS)
    })

    it('keeps parked tests visible below the table instead of dropping them', () => {
        const blocks = buildBlocks(
            new Date('2026-07-27T00:00:00Z'),
            [],
            [{ selector: 'masked.py::test_masked', trunk: { quarantinedAt: '2026-07-13T17:12:22.000Z' } }]
        )
        // Actions always sets GITHUB_WORKFLOW_REF, which appends a block after the parked note,
        // so find the note by content rather than by position.
        const note = blocks
            .filter((block) => block.type === 'context')
            .map((block) => block.elements[0].text)
            .find((text) => text.includes('quarantined in Trunk'))

        assert.equal(
            blocks.find((block) => block.type === 'table'),
            undefined
        )
        assert.match(note, /1 test is quarantined in Trunk/)
        assert.match(note, /test_masked/)
        assert.match(note, /Oldest parked 2026-07-13\./)
    })
})

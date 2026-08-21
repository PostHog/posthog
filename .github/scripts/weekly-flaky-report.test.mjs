import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    buildBlocks,
    buildQueue,
    buildRunnerReports,
    CLUSTER_MIN_TESTS,
    enrich,
    enrichRunnerCandidates,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    REPORT_RUNNERS,
    selectReportCandidates,
    tableRows,
    testStatusFor,
} from './weekly-flaky-report.mjs'
import { repoPathResolver, trackedTestPaths } from './weekly-report-common.mjs'

const onMasterResolver = (path) => [path]

describe('weekly flaky report', () => {
    it('builds runner-specific endpoint URLs before the endpoint limit', () => {
        const pytestUrl = flakyTestsUrl('pytest')
        const jestUrl = flakyTestsUrl('jest')

        assert.deepEqual(REPORT_RUNNERS, ['pytest', 'jest'])
        assert.equal(pytestUrl.searchParams.get('runner'), 'pytest')
        assert.equal(jestUrl.searchParams.get('runner'), 'jest')
        assert.equal(jestUrl.searchParams.get('repo'), 'PostHog/posthog')
        assert.equal(jestUrl.searchParams.get('limit'), '100')
    })

    it('builds a Slack table with supported cells and structured links', () => {
        const rows = tableRows(
            [
                {
                    runner: 'pytest',
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
        assert.deepEqual(
            table.rows[0].map((tableCell) => tableCell.text),
            ['test', 'runner', 'owner', 'rescued', 'fails', 'logs']
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
                            url: 'https://github.com/PostHog/posthog/blob/master/posthog/test/test_example.py',
                            text: 'test_report',
                        },
                    ],
                },
            ],
        })
        assert.deepEqual(rows[0][1], { type: 'raw_text', text: 'pytest' })
        assert.deepEqual(rows[0][5], {
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
            selectReportCandidates(items, 'pytest', onMasterResolver).map((candidate) => candidate.selector),
            ['test_proved.py::test_proved']
        )
        assert.deepEqual(
            selectReportCandidates(items, 'jest', onMasterResolver).map((candidate) => candidate.selector),
            ['test_report.ts']
        )
    })

    it('drops a test whose file only exists on the branch that added it', () => {
        const common = {
            classification: 'suspected_regression',
            failed_run_count: 6,
            failed_pr_count: 3,
            master_failed_run_count: 0,
            quarantined_failed_run_count: 0,
        }
        const items = [
            { ...common, runner: 'jest', selector: 'frontend/src/shared.test.tsx::shared flakes' },
            { ...common, runner: 'jest', selector: 'products/new/frontend/Unmerged.test.tsx::Unmerged explains itself' },
        ]
        const toRepoPaths = (path) => (path === 'frontend/src/shared.test.tsx' ? [path] : [])

        assert.deepEqual(
            selectReportCandidates(items, 'jest', toRepoPaths).map((candidate) => candidate.selector),
            ['frontend/src/shared.test.tsx::shared flakes']
        )
    })

    it('fetches each runner into its own candidate pool', async () => {
        const requestedRunners = []
        const pools = await fetchCandidatePools(['pytest', 'jest'], onMasterResolver, async (runner) => {
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

    it('ranks and limits each runner independently', async () => {
        const candidatePools = ['pytest', 'jest'].map((runner) => ({
            runner,
            candidates: Array.from({ length: 12 }, (_, index) => ({
                runner,
                selector: `${runner}-${index}`,
                failed_run_count: index === 10 ? 20 : 5,
            })),
        }))
        const runnerReports = await buildRunnerReports(candidatePools, async () => (item) => ({
            runsRescued: item.selector.endsWith('-11') ? 1 : 0,
            evidence: [],
        }))

        for (const { runner, candidates } of runnerReports) {
            assert.equal(candidates.length, 10)
            assert.deepEqual(
                candidates.map((candidate) => candidate.selector),
                [`${runner}-11`, `${runner}-10`, ...Array.from({ length: 8 }, (_, index) => `${runner}-${index}`)]
            )
        }
        assert.deepEqual(
            runnerReports.flatMap(({ candidates }) => candidates.map((candidate) => candidate.runner)),
            [...Array(10).fill('pytest'), ...Array(10).fill('jest')]
        )
    })

    it('resolves tracked Python and JavaScript-family test paths', () => {
        let gitArguments
        const expectedPaths = [
            'posthog/test/test_report.py',
            'frontend/src/report.test.js',
            'frontend/src/report.test.jsx',
            'frontend/src/report.test.ts',
            'frontend/src/report.test.tsx',
        ]
        const trackedPaths = trackedTestPaths((command, args) => {
            gitArguments = { command, args }
            return expectedPaths.join('\n')
        })
        const toRepoPaths = repoPathResolver(trackedPaths)

        assert.deepEqual(gitArguments, {
            command: 'git',
            args: ['ls-files', '*.py', '*.js', '*.jsx', '*.ts', '*.tsx'],
        })
        for (const path of expectedPaths) {
            assert.deepEqual(toRepoPaths(path), [path])
        }
        assert.deepEqual(toRepoPaths('src/report.test.tsx'), ['frontend/src/report.test.tsx'])
    })

    it('omits unsupported Jest enrichment and renders fallback cells', async () => {
        let enrichmentRequested = false
        const item = {
            runner: 'jest',
            selector: 'frontend/src/report.test.ts::renders the report',
            classification: 'confirmed_flake',
            quarantined_failed_run_count: 0,
            failed_run_count: 3,
        }
        const extrasFor = await enrichRunnerCandidates('jest', [item], async () => {
            enrichmentRequested = true
            return { results: [] }
        })
        const [row] = tableRows(
            [item],
            () => ({ owner: 'team-devex', repoPath: 'frontend/src/report.test.ts' }),
            extrasFor
        )

        assert.equal(enrichmentRequested, false)
        assert.deepEqual(row[1], { type: 'raw_text', text: 'Jest' })
        assert.deepEqual(row[3], { type: 'raw_text', text: '-' })
        assert.deepEqual(row[5], { type: 'raw_text', text: '-' })
    })

    it('scopes enrichment to the current repository', async () => {
        let request
        await enrich([{ selector: 'products/example/backend/test_report.py::test_report' }], async (query, values) => {
            request = { query, values }
            return { results: [] }
        })

        assert.match(request.query, /lower\(f\.repo\) = lower\(\{repository\}\)/)
        assert.equal(request.values.repository, 'PostHog/posthog')
        // Every path suffix, so either side of the join can carry the longer prefix.
        assert.deepEqual(request.values.selectors, [
            'products/example/backend/test_report.py::test_report',
            'example/backend/test_report.py::test_report',
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

    it('drops both quarantine systems from the queue, but keeps a Trunk flag that still fails CI', () => {
        const quarantineFile = { runner: 'pytest', selector: 'file.py::test_file', classification: 'quarantined' }
        // Quarantined earlier in the window, un-quarantined since, and failing on its own now.
        const unparked = {
            runner: 'pytest',
            selector: 'expired.py::test_expired',
            classification: 'quarantined',
            quarantined_failed_run_count: 3,
            failed_run_count: 4,
        }
        const trunked = { runner: 'pytest', selector: 'masked.py::test_masked', failed_run_count: 9 }
        const plain = { runner: 'pytest', selector: 'plain.py::test_plain', failed_run_count: 1 }
        const items = [quarantineFile, unparked, trunked, plain]
        const trunkFor = (item) =>
            item.selector === trunked.selector ? { quarantinedAt: '2026-07-13T17:12:22.000Z' } : null
        const selectors = (list) => list.map((item) => item.selector)

        const masked = buildQueue(items, testStatusFor(trunkFor, true))
        const unmasked = buildQueue(items, testStatusFor(trunkFor, false))

        assert.deepEqual(selectors(masked), [unparked.selector, plain.selector])
        // Masking off leaves Trunk's failure reddening CI, so only the quarantine file parks.
        assert.deepEqual(selectors(unmasked), [unparked.selector, trunked.selector, plain.selector])
        const [ownerCell] = tableRows(
            [trunked],
            () => ({ owner: 'team-devex', repoPath: null }),
            () => ({ runsRescued: null, evidence: [] }),
            testStatusFor(trunkFor, false)
        ).map((row) => row[2])
        assert.equal(ownerCell.text, 'devex (Trunk flagged)')
    })

    it('parks a quarantined test that would otherwise be buried in a collapsed cluster', () => {
        // A cluster's selector is a bare file path, so it can never match a test id.
        const items = Array.from({ length: CLUSTER_MIN_TESTS }, (_, index) => ({
            runner: 'pytest',
            selector: `shared.py::test_${index}`,
            failed_run_count: 2,
        }))

        const queue = buildQueue(
            items,
            testStatusFor(() => ({ quarantinedAt: '2026-07-13T17:12:22.000Z' }), true)
        )

        assert.deepEqual(queue, [])
    })

    it('matches a Jest selector reported from the package root against Trunk', async () => {
        const trunkFor = await fetchTrunkQuarantined(
            'jest',
            async () => ({
                results: [
                    [
                        'src/lib/components/ActivityLog/activityLogLogic.person.test.tsx::the activity log logic humanizing persons can handle addition of a property',
                        '2026-07-11T16:45:09.000Z',
                    ],
                ],
            }),
            true
        )

        assert.equal(
            trunkFor({
                selector:
                    'frontend/src/lib/components/ActivityLog/activityLogLogic.person.test.tsx::the activity log logic humanizing persons can handle addition of a property',
            }).quarantinedAt,
            '2026-07-11T16:45:09.000Z'
        )
    })

})

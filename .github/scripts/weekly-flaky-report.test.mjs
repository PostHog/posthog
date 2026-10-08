import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    buildBlocks,
    buildShadowBlocks,
    buildTeamDigests,
    buildRunnerReports,
    CLUSTER_MIN_TESTS,
    enrich,
    enrichRunnerCandidates,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    quarantineStatusFor,
    REPORT_RUNNERS,
    resolveFacts,
    selectReportCandidates,
    sharedTrunkLookup,
    tableRows,
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
        assert.equal(jestUrl.searchParams.get('limit'), '200')
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
                    failed_pr_count: 3,
                    same_commit_recovery_run_count: 2,
                },
            ],
            () => ({ owner: 'team-devex', repoPath: 'posthog/test/test_example.py' }),
            () => ({
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
            ['test', 'runner', 'owner', 'quarantine', 'PRs', 'failed runs', 'recovered runs', 'logs']
        )
        // The edit-workflow context block may still render when Actions env vars are set;
        // only the action footer has to be gone.
        const contextText = JSON.stringify(blocks.filter((block) => block.type === 'context'))
        assert.doesNotMatch(contextText, /fixing-flaky-tests|test:quarantine/)
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
        assert.deepEqual(rows[0][3], { type: 'raw_text', text: '-' })
        assert.deepEqual(rows[0][4], { type: 'raw_text', text: '3' })
        assert.deepEqual(rows[0][5], { type: 'raw_text', text: '4' })
        assert.deepEqual(rows[0][6], { type: 'raw_text', text: '2' })
        assert.deepEqual(rows[0][7], {
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

    it('selects on-master candidates for the requested runner', () => {
        const common = {
            failed_run_count: 4,
            failed_pr_count: 1,
            master_failed_run_count: 3,
            same_commit_recovery_run_count: 0,
            quarantined_failed_run_count: 0,
        }
        const items = [
            {
                ...common,
                runner: 'pytest',
                selector: 'test_proved.py::test_proved',
                classification: 'confirmed_flake',
                same_commit_recovery_run_count: 1,
            },
            {
                ...common,
                runner: 'pytest',
                selector: 'test_burst.py::test_burst',
                classification: 'suspected_regression',
            },
            {
                ...common,
                runner: 'pytest',
                selector: 'test_pr_only.py::test_pr_only',
                classification: 'suspected_regression',
                failed_pr_count: 4,
                master_failed_run_count: 0,
            },
            {
                ...common,
                runner: 'jest',
                selector: 'test_report.ts',
                classification: 'confirmed_flake',
                same_commit_recovery_run_count: 1,
            },
        ]

        assert.deepEqual(
            selectReportCandidates(items, 'pytest', onMasterResolver).map((candidate) => candidate.selector),
            ['test_proved.py::test_proved', 'test_burst.py::test_burst', 'test_pr_only.py::test_pr_only']
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
            same_commit_recovery_run_count: 0,
            quarantined_failed_run_count: 0,
        }
        const items = [
            { ...common, runner: 'jest', selector: 'frontend/src/shared.test.tsx::shared flakes' },
            {
                ...common,
                runner: 'jest',
                selector: 'products/new/frontend/Unmerged.test.tsx::Unmerged explains itself',
            },
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

    it('filters unproved regressions after an available Trunk lookup', async (context) => {
        const logs = context.mock.method(console, 'info', () => {})
        const common = {
            runner: 'pytest',
            classification: 'suspected_regression',
            failed_run_count: 6,
            failed_pr_count: 4,
            master_failed_run_count: 0,
            same_commit_recovery_run_count: 0,
            quarantined_failed_run_count: 0,
        }
        const plainRegressions = Array.from({ length: 40 }, (_, index) => ({
            ...common,
            selector: `${index < CLUSTER_MIN_TESTS ? 'shared.py' : `plain_${index}.py`}::test_${index}`,
        }))
        const trunked = { ...common, selector: 'trunked.py::test_trunked' }
        const confirmed = {
            ...common,
            selector: 'confirmed.py::test_confirmed',
            classification: 'confirmed_flake',
            same_commit_recovery_run_count: 1,
        }
        const expectedFailure = {
            ...common,
            selector: 'expected.py::test_marked_xfail_by_its_author',
            classification: 'quarantined',
            failed_run_count: 0,
            failed_pr_count: 0,
            quarantined_failed_run_count: 2,
        }
        const master = {
            ...common,
            selector: 'master.py::test_master',
            failed_pr_count: 1,
            master_failed_run_count: 4,
        }
        const trunkedMaster = { ...master, selector: 'trunked_master.py::test_trunked_master' }
        const getEnrichment = async () => () => ({ evidence: [] })
        const candidatePools = await fetchCandidatePools(['pytest'], onMasterResolver, async () => ({
            items: [...plainRegressions, trunked, confirmed, expectedFailure, master, trunkedMaster],
        }))
        const [{ candidates }] = await buildRunnerReports(
            candidatePools,
            getEnrichment,
            async () => (item) =>
                item === trunked || item === trunkedMaster ? { quarantinedAt: '2026-07-13T17:12:22.000Z' } : null
        )

        assert.deepEqual(
            candidates.map((candidate) => [candidate.selector, candidate.failed_run_count]),
            [
                [confirmed.selector, 6],
                [trunked.selector, 6],
                [trunkedMaster.selector, 6],
            ]
        )
        assert.ok(logs.mock.calls.some(({ arguments: [message] }) => message.includes(expectedFailure.selector)))

        const [{ candidates: candidatesWithoutTrunk }] = await buildRunnerReports(
            [{ runner: 'pytest', candidates: [plainRegressions[0], expectedFailure, master] }],
            getEnrichment,
            async () => null
        )
        assert.deepEqual(
            candidatesWithoutTrunk.map((candidate) => candidate.selector),
            [plainRegressions[0].selector]
        )
    })

    it('ranks and limits each runner independently', async () => {
        const candidatePools = ['pytest', 'jest'].map((runner) => ({
            runner,
            candidates: Array.from({ length: 12 }, (_, index) => ({
                runner,
                selector: `${runner}-${index}`,
                failed_run_count: index === 10 ? 20 : 5,
                same_commit_recovery_run_count: index === 11 ? 3 : 1,
            })),
        }))
        const runnerReports = await buildRunnerReports(
            candidatePools,
            async () => () => ({ evidence: [] }),
            async () => null
        )

        for (const { runner, candidates } of runnerReports) {
            assert.equal(candidates.length, 10)
            assert.deepEqual(
                candidates.map((candidate) => candidate.selector),
                [`${runner}-10`, `${runner}-11`, ...Array.from({ length: 8 }, (_, index) => `${runner}-${index}`)]
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
            same_commit_recovery_run_count: 1,
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
        assert.deepEqual(row[7], { type: 'raw_text', text: '-' })
    })

    it('scopes enrichment and links the latest distinct failing runs', async () => {
        let request
        const item = { selector: 'products/example/backend/test_report.py::test_report' }
        const extrasFor = await enrich([item], async (query, values) => {
            request = { query, values }
            return {
                results: [
                    [
                        item.selector,
                        [
                            [100, 10, 20],
                            [300, 12, 22],
                            [250, 12, 23],
                            [200, 11, 21],
                        ],
                    ],
                ],
            }
        })

        assert.deepEqual(extrasFor(item), {
            evidence: [
                { runId: 12, jobId: 22 },
                { runId: 11, jobId: 21 },
            ],
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

    it('distinguishes unavailable Trunk data from an empty result', async () => {
        const otherRunnerOnly = {
            available: true,
            truncated: false,
            ttl_days: 15,
            tests: [{ runner: 'jest', nodeid: 'posthog/test/test_example.py::test_report', quarantined_at: null }],
        }
        const cases = [
            {
                label: 'uploads off',
                enabled: false,
                available: false,
                fetchQuarantine: () => assert.fail('must not query Trunk while uploads are disabled'),
            },
            {
                label: 'request fails',
                enabled: true,
                available: false,
                fetchQuarantine: async () => {
                    throw new Error('trunk_quarantine 503')
                },
            },
            {
                label: 'no Trunk source synced',
                enabled: true,
                available: false,
                fetchQuarantine: async () => ({ ...otherRunnerOnly, available: false, tests: [] }),
            },
            {
                label: 'list is cut short, so rows may be missing',
                enabled: true,
                available: false,
                fetchQuarantine: async () => ({ ...otherRunnerOnly, truncated: true, limit: 5000 }),
            },
            {
                label: 'only another runner is quarantined',
                enabled: true,
                available: true,
                fetchQuarantine: async () => otherRunnerOnly,
            },
        ]

        for (const { label, enabled, available, fetchQuarantine } of cases) {
            const trunkFor = await fetchTrunkQuarantined('pytest', fetchQuarantine, enabled)

            assert.equal(typeof trunkFor === 'function', available, label)
            assert.equal(trunkFor?.({ selector: 'posthog/test/test_example.py::test_report' }) ?? null, null, label)
        }
    })

    it('matches Trunk rows to a product suite reported product-relative', async () => {
        let requests = 0
        const getTrunk = sharedTrunkLookup(async () => {
            requests += 1
            return {
                available: true,
                truncated: false,
                ttl_days: 15,
                tests: [
                    {
                        runner: 'pytest',
                        nodeid: 'products/example/backend/tests/test_migration.py::MigrationTest::test_backfill',
                        quarantined_at: '2026-07-29T09:14:22Z',
                        overdue: true,
                    },
                    {
                        runner: 'jest',
                        nodeid: 'src/scenes/example/exampleLogic.test.ts::exampleLogic loads the example',
                        quarantined_at: '2026-07-31T11:00:00Z',
                        overdue: false,
                    },
                ],
            }
        }, true)
        const pytestFor = await getTrunk('pytest')
        const jestFor = await getTrunk('jest')

        // The endpoint is not runner-specific, so a second request would repeat the first.
        assert.equal(requests, 1)
        assert.deepEqual(pytestFor({ selector: 'backend/tests/test_migration.py::MigrationTest::test_backfill' }), {
            quarantinedAt: '2026-07-29T09:14:22Z',
            overdue: true,
            fixBy: '2026-08-13',
        })
        assert.equal(pytestFor({ selector: 'backend/tests/test_migration.py::MigrationTest::test_other' }), null)
        assert.equal(
            pytestFor({ selector: 'frontend/src/scenes/example/exampleLogic.test.ts::exampleLogic loads the example' }),
            null
        )
        assert.equal(
            jestFor({ selector: 'frontend/src/scenes/example/exampleLogic.test.ts::exampleLogic loads the example' })
                .fixBy,
            '2026-08-15'
        )
    })

    it('labels how Trunk suppresses a test instead of dropping it', () => {
        const trunked = { runner: 'pytest', selector: 'masked.py::test_masked', failed_run_count: 9 }
        const overdue = { runner: 'pytest', selector: 'overdue.py::test_overdue', failed_run_count: 7 }
        const unlimited = { runner: 'pytest', selector: 'unlimited.py::test_unlimited', failed_run_count: 3 }
        const undated = { runner: 'pytest', selector: 'undated.py::test_undated', failed_run_count: 2 }
        const plain = { runner: 'pytest', selector: 'plain.py::test_plain', failed_run_count: 1 }
        const items = [trunked, overdue, unlimited, undated, plain]
        const trunkRows = new Map([
            [trunked.selector, { quarantinedAt: '2026-07-13T17:12:22Z', overdue: false, fixBy: '2026-07-28' }],
            [overdue.selector, { quarantinedAt: '2026-06-20T08:00:00Z', overdue: true, fixBy: '2026-07-05' }],
            [unlimited.selector, { quarantinedAt: '2026-07-13T17:12:22Z', overdue: false, fixBy: null }],
            [undated.selector, { quarantinedAt: null, overdue: false, fixBy: null }],
        ])
        const trunkFor = (item) => trunkRows.get(item.selector) || null

        const cells = (masksCi) =>
            tableRows(
                resolveFacts(items, trunkFor),
                () => ({ owner: 'team-devex', repoPath: null }),
                () => ({ evidence: [] }),
                (item) => quarantineStatusFor(item, masksCi)
            ).map((row) => row[3].text)

        assert.deepEqual(cells(true), ['fix by 2026-07-28', 'overdue since 2026-07-05', 'since 2026-07-13', 'yes', '-'])
        // Masking off leaves Trunk's failure reddening CI, so the date would overclaim.
        assert.deepEqual(cells(false), ['flagged', 'flagged', 'flagged', 'flagged', '-'])
    })

    it('keeps a Trunk-quarantined test in the report and counts suppressed cluster members', async () => {
        const clustered = Array.from({ length: CLUSTER_MIN_TESTS }, (_, index) => ({
            runner: 'pytest',
            classification: 'confirmed_flake',
            selector: `shared.py::test_${index}`,
            // The first two members are listed in Trunk.
            failed_run_count: index < 2 ? 3 : 2,
            quarantined_failed_run_count: 0,
            same_commit_recovery_run_count: 1,
            master_failed_run_count: 0,
            failed_pr_count: 1,
        }))
        const trunked = {
            runner: 'pytest',
            selector: 'masked.py::test_masked',
            classification: 'suspected_regression',
            failed_run_count: 9,
            failed_pr_count: 4,
            master_failed_run_count: 0,
            same_commit_recovery_run_count: 0,
            quarantined_failed_run_count: 0,
        }
        const listed = new Set([trunked.selector, clustered[0].selector, clustered[1].selector])
        const report = async (masksCi) => {
            const [{ candidates }] = await buildRunnerReports(
                [{ runner: 'pytest', candidates: [...clustered, trunked] }],
                async () => () => ({ evidence: [] }),
                async () => (item) =>
                    listed.has(item.selector) ? { quarantinedAt: '2026-07-13T17:12:22.000Z' } : null,
                masksCi
            )
            return candidates
        }
        const candidates = await report(true)

        // Members share runs, so the cluster reports the largest member count and not the sum.
        assert.deepEqual(
            candidates.map((candidate) => [candidate.selector, candidate.failed_run_count]),
            [
                ['masked.py::test_masked', 9],
                ['shared.py', 3],
            ]
        )
        assert.deepEqual(
            candidates.map((candidate) => quarantineStatusFor(candidate, true)),
            ['since 2026-07-13', `2/${CLUSTER_MIN_TESTS}`]
        )
        // A Trunk-marked member with masking off is only 'flagged' and must not count as suppressed.
        assert.deepEqual(
            (await report(false)).map((candidate) => quarantineStatusFor(candidate, false)),
            ['flagged', null]
        )
        const [clusterRow] = tableRows(
            [candidates[1]],
            () => ({ owner: 'team-devex', repoPath: null }),
            () => ({ evidence: [] })
        )
        // The cluster counts are floors over overlapping member sets, never exact counts.
        assert.deepEqual(clusterRow[4], { type: 'raw_text', text: '1+' })
        assert.deepEqual(clusterRow[5], { type: 'raw_text', text: '3+' })
    })

    it('groups shadow digests by owning team and drops teams it cannot route', () => {
        const row = (name) => [{ type: 'raw_text', text: name }]
        const entries = [
            { owner: 'team-devex', slack: '#team-devex', row: row('test_one') },
            { owner: 'team-devex', slack: '#team-devex', row: row('test_two') },
            { owner: 'team-replay', slack: '#team-replay', row: row('renders') },
            { owner: 'unowned', slack: null, row: row('test_orphan') },
            // notifications: false, owned but the team declared no automation channel.
            { owner: 'team-quiet', slack: null, row: row('test_silenced') },
        ]

        const digests = buildTeamDigests(entries)

        assert.deepEqual(
            digests.map(({ owner, channel, rows }) => [owner, channel, rows.length]),
            [
                ['team-devex', '#team-devex', 2],
                ['team-replay', '#team-replay', 1],
            ]
        )
        const [header, table] = buildShadowBlocks(digests[0])
        assert.equal(header.text.text, '*devex* _(shadow: would post to #team-devex)_')
        assert.equal(table.rows.length, 3)
    })

    it('matches a Jest selector reported from the package root against Trunk', async () => {
        const trunkFor = await fetchTrunkQuarantined(
            'jest',
            async () => ({
                available: true,
                truncated: false,
                // Without a time limit there is no fix-by date to report.
                ttl_days: null,
                tests: [
                    {
                        runner: 'jest',
                        nodeid: 'src/lib/components/ActivityLog/activityLogLogic.person.test.tsx::the activity log logic humanizing persons can handle addition of a property',
                        quarantined_at: '2026-07-11T16:45:09.000Z',
                        overdue: false,
                    },
                ],
            }),
            true
        )

        assert.deepEqual(
            trunkFor({
                selector:
                    'frontend/src/lib/components/ActivityLog/activityLogLogic.person.test.tsx::the activity log logic humanizing persons can handle addition of a property',
            }),
            { quarantinedAt: '2026-07-11T16:45:09.000Z', overdue: false, fixBy: null }
        )
    })
})

import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataQualityChecksHealthList,
    dataQualityChecksList,
    dataQualityRunsCreate,
    dataQualityRunsRetrieve,
    warehouseSavedQueriesChecksDestroy,
    warehouseSavedQueriesChecksRunsList,
} from 'products/data_quality/frontend/generated/api'
import type {
    DataQualityOverviewCheckApi,
    DataQualitySuiteRunApi,
} from 'products/data_quality/frontend/generated/api.schemas'

import {
    dataQualityOverviewLogic,
    focusCandidatesAfterDelete,
    rowActionsId,
    subjectDetailUrl,
    subjectDisclosureId,
} from './dataQualityOverviewLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
    ApiError: class ApiError extends Error {},
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('products/data_quality/frontend/generated/api', () => ({
    dataQualityChecksList: jest.fn(),
    dataQualityChecksHealthList: jest.fn(),
    dataQualityRunsCreate: jest.fn(),
    dataQualityRunsRetrieve: jest.fn(),
    warehouseSavedQueriesChecksDestroy: jest.fn(),
    warehouseTablesChecksDestroy: jest.fn(),
    warehouseSavedQueriesChecksRunsList: jest.fn(),
    warehouseTablesChecksRunsList: jest.fn(),
}))

function buildCheck(
    id: string,
    subject: string,
    lastStatus: string | null,
    overrides: Partial<DataQualityOverviewCheckApi> = {}
): DataQualityOverviewCheckApi {
    return {
        id,
        name: `${subject}_check`,
        subject_type: 'view',
        subject_uuid: `uuid-${subject}`,
        subject_name: subject,
        check_type: 'not_null',
        column_name: 'id',
        severity: 'error',
        enabled: true,
        last_status: lastStatus ?? '',
        last_run_at: null,
        subject_node_id: null,
        subject_source_id: null,
        subject_schema_id: null,
        ...overrides,
    } as DataQualityOverviewCheckApi
}

function buildSuiteRun(overrides: Partial<DataQualitySuiteRunApi> = {}): DataQualitySuiteRunApi {
    return {
        id: 'suite-1',
        status: 'running',
        trigger: 'manual',
        checks_passed: 0,
        checks_failed: 0,
        checks_errored: 0,
        checks_skipped: 0,
        error: '',
        ...overrides,
    } as DataQualitySuiteRunApi
}

const HEALTH = [
    { subject_type: 'view', subject_uuid: 'uuid-orders', health: 'failing', checks_total: 2, checks_failing: 1 },
    { subject_type: 'view', subject_uuid: 'uuid-customers', health: 'healthy', checks_total: 1, checks_failing: 0 },
]

describe('dataQualityOverviewLogic', () => {
    let logic: ReturnType<typeof dataQualityOverviewLogic.build>

    async function mountLogic(): Promise<void> {
        initKeaTests()
        logic = dataQualityOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [
                buildCheck('check-1', 'orders', 'failed'),
                buildCheck('check-2', 'orders', 'passed'),
                buildCheck('check-3', 'customers', null),
            ],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue(HEALTH)
    })

    afterEach(() => {
        jest.useRealTimers()
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('keys subjects by type and uuid together, since the two kinds can collide', async () => {
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [
                buildCheck('check-1', 'orders', 'failed'),
                buildCheck('check-2', 'orders_table', 'passed', {
                    subject_type: 'table',
                    subject_uuid: 'uuid-orders',
                }),
            ],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([
            {
                subject_type: 'view',
                subject_uuid: 'uuid-orders',
                health: 'failing',
                checks_total: 1,
                checks_failing: 1,
            },
            {
                subject_type: 'table',
                subject_uuid: 'uuid-orders',
                health: 'healthy',
                checks_total: 1,
                checks_failing: 0,
            },
        ])
        await mountLogic()

        expect(logic.values.subjectGroups.map((group) => [group.subjectKey, group.health])).toEqual([
            ['view:uuid-orders', 'failing'],
            ['table:uuid-orders', 'healthy'],
        ])
    })

    it('groups checks by subject, worst health first', async () => {
        // The rollup belongs to the subject, so it has to be carried on the group rather than on
        // every row; and a healthy subject must not push a failing one down the page.
        await mountLogic()

        expect(
            logic.values.subjectGroups.map((group) => [group.subjectName, group.health, group.checks.length])
        ).toEqual([
            ['orders', 'failing', 2],
            ['customers', 'healthy', 1],
        ])
    })

    it('opens only the subjects that need attention, once', async () => {
        await mountLogic()

        expect(logic.values.expandedSubjectKeys).toEqual(['view:uuid-orders'])
    })

    it.each<[string, Record<string, unknown>, string[]]>([
        ['failing only', { status: 'failing' }, ['check-1']],
        ['never run', { status: 'never_run' }, ['check-3']],
        ['a search over the subject', { search: 'customers' }, ['check-3']],
    ])('filters to %s', async (_case, filters, expectedIds) => {
        await mountLogic()

        logic.actions.setFilters(filters)

        expect(logic.values.filteredChecks.map((check) => check.id)).toEqual(expectedIds)
    })

    it('draws the failing ratio from the rollup, not the filtered rows, so it cannot invert', async () => {
        // Filtering to never-run checks leaves fewer rows than the subject has failing, so a
        // denominator taken from the filtered rows would print an impossible "2 of 1 failing".
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [
                buildCheck('check-1', 'orders', 'failed'),
                buildCheck('check-2', 'orders', 'failed'),
                buildCheck('check-3', 'orders', null),
            ],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([
            {
                subject_type: 'view',
                subject_uuid: 'uuid-orders',
                health: 'failing',
                checks_total: 3,
                checks_failing: 2,
            },
        ])
        await mountLogic()
        logic.actions.setFilters({ status: 'never_run' })

        const [group] = logic.values.subjectGroups
        expect(group.checks).toHaveLength(1)
        expect(group.checksFailing).toEqual(2)
        expect(group.checksTotal).toEqual(3)
    })

    it('keeps subjects the user opened through filtering and refreshing', async () => {
        await mountLogic()
        logic.actions.toggleSubjectExpanded('view:uuid-customers')

        logic.actions.setFilters({ search: 'orders' })
        logic.actions.loadOverview()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.expandedSubjectKeys).toEqual(['view:uuid-orders', 'view:uuid-customers'])
    })

    it('drops expanded subjects that no longer exist', async () => {
        await mountLogic()
        logic.actions.toggleSubjectExpanded('view:uuid-customers')
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [buildCheck('check-1', 'orders', 'failed')],
        })

        logic.actions.loadOverview()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.expandedSubjectKeys).toEqual(['view:uuid-orders'])
    })

    it.each<[string, boolean, boolean]>([
        ['the checks call', true, false],
        ['the health call', false, true],
    ])('shows the retry state when %s fails on first load', async (_case, checksFails, healthFails) => {
        if (checksFails) {
            ;(dataQualityChecksList as jest.Mock).mockRejectedValue(new Error('down'))
        }
        if (healthFails) {
            ;(dataQualityChecksHealthList as jest.Mock).mockRejectedValue(new Error('down'))
        }
        await mountLogic()

        expect(logic.values.snapshotLoaded).toBe(false)
        expect(logic.values.overviewError).toBeTruthy()
        expect(logic.values.checks).toEqual([])
    })

    it.each<[string, boolean, boolean]>([
        ['the checks call', true, false],
        ['the health call', false, true],
    ])('keeps the last consistent snapshot when %s fails on refresh', async (_case, checksFails, healthFails) => {
        await mountLogic()
        if (checksFails) {
            ;(dataQualityChecksList as jest.Mock).mockRejectedValue(new Error('down'))
        }
        if (healthFails) {
            ;(dataQualityChecksHealthList as jest.Mock).mockRejectedValue(new Error('down'))
        }

        logic.actions.loadOverview()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.snapshotLoaded).toBe(true)
        expect(logic.values.overviewError).toBeTruthy()
        expect(logic.values.checks).toHaveLength(3)
        expect(logic.values.subjectHealth).toHaveLength(2)
    })

    it('summarises a project that has failing checks', async () => {
        await mountLogic()

        expect(logic.values.overviewSummary).toEqual('1 of 3 checks failing, across 1 tables and views.')
    })

    it('counts a subject whose only failure is warning-only among the failing subjects', async () => {
        // A warn-severity failure raises the failing-check count but leaves the subject's health at
        // 'warn', so a subject count taken from the health rollup read "1 of 1 checks failing,
        // across 0 tables and views".
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [buildCheck('check-1', 'orders', 'failed', { severity: 'warn' })],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([
            { subject_type: 'view', subject_uuid: 'uuid-orders', health: 'warn', checks_total: 1, checks_failing: 0 },
        ])
        await mountLogic()

        expect(logic.values.failingCheckCount).toEqual(1)
        expect(logic.values.failingSubjectCount).toEqual(1)
        expect(logic.values.overviewSummary).toEqual('1 of 1 checks failing, across 1 tables and views.')
    })

    it.each<[string, (string | null)[], string]>([
        // The regression: a not-failing check was reported as passed, so a page of never-run checks
        // read as an all-clear the moment they were created.
        ['never-run checks as not run, never as passed', [null, null], 'None of your checks have run yet.'],
        ['a fully passing project as all passed', ['passed', 'passed'], 'All 2 checks passed on their last run.'],
        [
            'a mix without claiming the unrun ones passed',
            ['passed', null],
            '1 of 2 checks passed on their last run, 1 not run yet.',
        ],
    ])('summarises %s', async (_case, statuses, expected) => {
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: statuses.map((status, index) => buildCheck(`check-${index}`, 'orders', status)),
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([])
        await mountLogic()

        expect(logic.values.overviewSummary).toEqual(expected)
    })

    it('sends no ids when running everything', async () => {
        // An empty list is what the endpoint reads as "every enabled check", so it must not be
        // replaced by the currently filtered rows.
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(
            buildSuiteRun({ status: 'completed', checks_passed: 3 })
        )
        await mountLogic()
        logic.actions.setFilters({ status: 'failing' })

        logic.actions.runChecks({ kind: 'all' })
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityRunsCreate).toHaveBeenCalledWith('1', { check_ids: [] })
    })

    it('reports a subject run into that subject alone', async () => {
        // The regression: one global spinner meant every run control span every panel.
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        await mountLogic()

        logic.actions.runChecks({ kind: 'subject', subjectKey: 'view:uuid-orders' }, ['check-1', 'check-2'])
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityRunsCreate).toHaveBeenCalledWith('1', { check_ids: ['check-1', 'check-2'] })
        expect(logic.values.runningSubjectKey).toEqual('view:uuid-orders')
        expect(logic.values.runTarget).toEqual({ kind: 'subject', subjectKey: 'view:uuid-orders' })
    })

    it('runs one check without pulling in the rest of its subject', async () => {
        // Fixing one broken check and re-running just that check is the loop this page exists for.
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        await mountLogic()

        logic.actions.runChecks({ kind: 'subject', subjectKey: 'view:uuid-orders' }, ['check-1'])
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityRunsCreate).toHaveBeenCalledWith('1', { check_ids: ['check-1'] })
        expect(logic.values.runningSubjectKey).toEqual('view:uuid-orders')
    })

    it('offers a retry instead of a toast when a run cannot start', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockRejectedValue(new Error('down'))
        await mountLogic()

        logic.actions.runChecks({ kind: 'all' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runError).toEqual("Couldn't run checks.")
        expect(logic.values.startingRun).toBe(false)
        expect(logic.values.runningSubjectKey).toBeNull()
    })

    it('removes a deleted check and refreshes the snapshot', async () => {
        ;(warehouseSavedQueriesChecksDestroy as jest.Mock).mockResolvedValue(undefined)
        await mountLogic()
        const loadsBeforeDelete = (dataQualityChecksList as jest.Mock).mock.calls.length

        logic.actions.deleteCheck(buildCheck('check-1', 'orders', 'failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksDestroy).toHaveBeenCalledWith('1', 'uuid-orders', 'check-1')
        expect((dataQualityChecksList as jest.Mock).mock.calls.length).toBeGreaterThan(loadsBeforeDelete)
        expect(lemonToast.success).toHaveBeenCalledWith('Check deleted')
    })

    it('keeps the row and says so when a delete fails', async () => {
        ;(warehouseSavedQueriesChecksDestroy as jest.Mock).mockRejectedValue(new Error('down'))
        await mountLogic()

        logic.actions.deleteCheck(buildCheck('check-1', 'orders', 'failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checks.map((check) => check.id)).toEqual(['check-1', 'check-2', 'check-3'])
        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.deletingCheckIds['check-1']).toBe(false)
    })

    it('deletes a check once when the confirmation is submitted twice', async () => {
        ;(warehouseSavedQueriesChecksDestroy as jest.Mock).mockResolvedValue(undefined)
        await mountLogic()
        const check = buildCheck('check-1', 'orders', 'failed')

        logic.actions.deleteCheck(check)
        logic.actions.deleteCheck(check)
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksDestroy).toHaveBeenCalledTimes(1)
    })

    it('reloads the rows once the polled run finishes', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(dataQualityRunsRetrieve as jest.Mock)
            .mockResolvedValueOnce(buildSuiteRun())
            .mockResolvedValue(buildSuiteRun({ status: 'completed', checks_passed: 2, checks_failed: 1 }))
        await mountLogic()
        const loadsBeforeRun = (dataQualityChecksList as jest.Mock).mock.calls.length

        jest.useFakeTimers()
        logic.actions.runChecks({ kind: 'all' })
        await drainListeners()
        expect(logic.values.isRunning).toBe(true)

        await advancePoll(3000)
        await advancePoll(3000)

        expect(logic.values.isRunning).toBe(false)
        expect((dataQualityChecksList as jest.Mock).mock.calls.length).toBeGreaterThan(loadsBeforeRun)
        expect(lemonToast.warning).toHaveBeenCalledWith('2 passed, 1 failed')
    })

    it('refreshes the run history cached under expanded rows when a run finishes', async () => {
        // A row expanded before the run caches its history; loadOverview refreshes status and
        // rollups but not those runs, so without a reload the just-finished run is missing until a
        // collapse and re-expand.
        ;(warehouseSavedQueriesChecksRunsList as jest.Mock).mockResolvedValue([{ compiled_query: 'SELECT 1' }])
        await mountLogic()
        logic.actions.loadCheckRuns(buildCheck('check-1', 'orders', 'failed'))
        await expectLogic(logic).toFinishAllListeners()
        const runsLoadsBeforeFinish = (warehouseSavedQueriesChecksRunsList as jest.Mock).mock.calls.length

        logic.actions.finishSuiteRun(buildSuiteRun({ status: 'completed', checks_passed: 3 }))
        await expectLogic(logic).toFinishAllListeners()

        expect((warehouseSavedQueriesChecksRunsList as jest.Mock).mock.calls.length).toBeGreaterThan(
            runsLoadsBeforeFinish
        )
    })

    it('stops polling a run that never finishes', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(dataQualityRunsRetrieve as jest.Mock).mockResolvedValue(buildSuiteRun())
        await mountLogic()

        jest.useFakeTimers()
        logic.actions.runChecks({ kind: 'all' })
        await drainListeners()

        for (let poll = 0; poll < 80 && !logic.values.pollTimedOut; poll++) {
            await advancePoll(poll < 20 ? 3000 : 15000)
        }

        expect(logic.values.pollTimedOut).toBe(true)
        expect(logic.values.isRunning).toBe(false)
    })

    it.each<[string, Record<string, string>[], string | null]>([
        // Retention clears the compiled query of older runs first, so "latest" is not always [0].
        [
            'the newest run that still has one',
            [{ compiled_query: 'SELECT 2' }, { compiled_query: 'SELECT 1' }],
            'SELECT 2',
        ],
        ['past runs whose query was cleared', [{ compiled_query: '' }, { compiled_query: 'SELECT 1' }], 'SELECT 1'],
    ])('opens the failing rows of %s', async (_case, runs, expected) => {
        ;(warehouseSavedQueriesChecksRunsList as jest.Mock).mockResolvedValue(runs)
        await mountLogic()

        logic.actions.openFailingRows(buildCheck('check-1', 'orders', 'failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toMatch(/\/sql$/)
        expect(router.values.searchParams.open_query).toEqual(expected)
    })

    it.each<[string, Record<string, string>[]]>([
        ['the check has never run', []],
        ['every run has lost its query to retention', [{ compiled_query: '' }]],
    ])('says why there is nothing to open when %s', async (_case, runs) => {
        ;(warehouseSavedQueriesChecksRunsList as jest.Mock).mockResolvedValue(runs)
        await mountLogic()

        logic.actions.openFailingRows(buildCheck('check-1', 'orders', 'failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.info).toHaveBeenCalled()
        expect(router.values.location.pathname).not.toMatch(/\/sql$/)
    })

    it.each<[string, Partial<DataQualityOverviewCheckApi>, string | null]>([
        ['a view on a DAG node', { subject_type: 'view', subject_node_id: 'node-1' }, '/models/node-1'],
        ['a view on no DAG', { subject_type: 'view', subject_node_id: null }, null],
        [
            'a synced table',
            { subject_type: 'table', subject_source_id: 'source-1', subject_schema_id: 'schema-1' },
            '/data-management/sources/source-1/schemas/schema-1',
        ],
        [
            'a table linked by hand rather than synced',
            { subject_type: 'table', subject_uuid: 'uuid-table', subject_source_id: null },
            '/data-management/sources/self-managed-uuid-table/schemas',
        ],
    ])('links %s', (_case, overrides, expected) => {
        expect(subjectDetailUrl(buildCheck('check-1', 'orders', null, overrides))).toEqual(expected)
    })

    it.each<[string, string, string]>([
        ['the next check in the same subject', 'check-1', rowActionsId('check-2')],
        ['the previous check when the last one goes', 'check-2', rowActionsId('check-1')],
    ])('restores focus to %s', async (_case, deletedId, expectedFirst) => {
        await mountLogic()

        const candidates = focusCandidatesAfterDelete(logic.values.subjectGroups, 'view:uuid-orders', deletedId)

        expect(candidates[0]).toEqual(expectedFirst)
    })

    it('falls back past the emptied subject to its neighbour, then the empty state', async () => {
        await mountLogic()

        const candidates = focusCandidatesAfterDelete(logic.values.subjectGroups, 'view:uuid-customers', 'check-3')

        expect(candidates).toEqual([subjectDisclosureId('view:uuid-orders'), 'data-quality-browse-subjects'])
    })

    async function drainListeners(): Promise<void> {
        for (let tick = 0; tick < 20; tick++) {
            await Promise.resolve()
        }
    }

    async function advancePoll(ms: number): Promise<void> {
        jest.advanceTimersByTime(ms)
        await drainListeners()
    }
})

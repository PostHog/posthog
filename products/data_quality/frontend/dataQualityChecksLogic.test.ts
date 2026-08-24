import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import {
    warehouseSavedQueriesCheckSuiteRunsCheckRunsList,
    warehouseSavedQueriesCheckSuiteRunsList,
    warehouseSavedQueriesCheckSuiteRunsRetrieve,
    warehouseSavedQueriesChecksCheckTypesList,
    warehouseSavedQueriesChecksCreate,
    warehouseSavedQueriesChecksDestroy,
    warehouseSavedQueriesChecksHealthRetrieve,
    warehouseSavedQueriesChecksList,
    warehouseSavedQueriesChecksPartialUpdate,
    warehouseSavedQueriesChecksRunAllCreate,
    warehouseSavedQueriesChecksRunCreate,
    warehouseTablesCheckSuiteRunsList,
    warehouseTablesChecksHealthRetrieve,
    warehouseTablesChecksList,
} from './generated/api'
import type { DataQualityCheckApi, DataQualitySuiteRunApi } from './generated/api.schemas'
import { CheckTypeEnumApi } from './generated/api.schemas'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: {},
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('scenes/data-management/database/databaseTableListLogic', () => ({
    databaseTableListLogic: { loadDatabase: jest.fn(() => ({ type: 'load database (mock)' })) },
}))

jest.mock('./generated/api', () => ({
    warehouseSavedQueriesChecksList: jest.fn(),
    warehouseSavedQueriesChecksCreate: jest.fn(),
    warehouseSavedQueriesChecksPartialUpdate: jest.fn(),
    warehouseSavedQueriesChecksDestroy: jest.fn(),
    warehouseSavedQueriesChecksRunCreate: jest.fn(),
    warehouseSavedQueriesChecksRunAllCreate: jest.fn(),
    warehouseSavedQueriesChecksRunsList: jest.fn(),
    warehouseSavedQueriesChecksCheckTypesList: jest.fn(),
    warehouseSavedQueriesChecksHealthRetrieve: jest.fn(),
    warehouseSavedQueriesCheckSuiteRunsList: jest.fn(),
    warehouseSavedQueriesCheckSuiteRunsRetrieve: jest.fn(),
    warehouseSavedQueriesCheckSuiteRunsCheckRunsList: jest.fn(),
    warehouseTablesChecksList: jest.fn(),
    warehouseTablesChecksCreate: jest.fn(),
    warehouseTablesChecksPartialUpdate: jest.fn(),
    warehouseTablesChecksDestroy: jest.fn(),
    warehouseTablesChecksRunCreate: jest.fn(),
    warehouseTablesChecksRunAllCreate: jest.fn(),
    warehouseTablesChecksRunsList: jest.fn(),
    warehouseTablesChecksCheckTypesList: jest.fn(),
    warehouseTablesChecksHealthRetrieve: jest.fn(),
    warehouseTablesCheckSuiteRunsList: jest.fn(),
    warehouseTablesCheckSuiteRunsRetrieve: jest.fn(),
    warehouseTablesCheckSuiteRunsCheckRunsList: jest.fn(),
}))

const VIEW_PROPS: DataQualityChecksLogicProps = { subjectType: 'view', subjectId: 'view-1' }

const CHECK_TYPE_CATALOG = [
    { check_type: 'not_null', description: '', requires_column: true, config_schema: {} },
    { check_type: 'unique', description: '', requires_column: true, config_schema: {} },
    { check_type: 'accepted_values', description: '', requires_column: true, config_schema: {} },
    { check_type: 'relationships', description: '', requires_column: true, config_schema: {} },
    { check_type: 'row_count', description: '', requires_column: false, config_schema: {} },
    { check_type: 'freshness', description: '', requires_column: true, config_schema: {} },
    { check_type: 'custom_sql', description: '', requires_column: false, config_schema: {} },
]

function buildCheck(overrides: Partial<DataQualityCheckApi> = {}): DataQualityCheckApi {
    return {
        id: 'check-1',
        check_type: CheckTypeEnumApi.NotNull,
        column_name: 'customer_id',
        enabled: true,
        severity: 'error',
        last_status: '',
        config: {},
        tags: [],
        ...overrides,
    } as DataQualityCheckApi
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

function forbidden(): Error {
    const { ApiError } = jest.requireMock('lib/api')
    return new ApiError('Forbidden', 403, undefined, { detail: 'nope' })
}

describe('dataQualityChecksLogic', () => {
    let logic: ReturnType<typeof dataQualityChecksLogic.build>

    async function mountLogic(props: DataQualityChecksLogicProps = VIEW_PROPS): Promise<void> {
        initKeaTests()
        logic = dataQualityChecksLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    async function openFormWithCatalog(values: Record<string, unknown>): Promise<void> {
        logic.actions.openCheckModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues(values)
    }

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(warehouseSavedQueriesChecksList as jest.Mock).mockResolvedValue({ results: [buildCheck()] })
        ;(warehouseTablesChecksList as jest.Mock).mockResolvedValue({ results: [] })
        ;(warehouseSavedQueriesChecksHealthRetrieve as jest.Mock).mockResolvedValue({
            health: 'healthy',
            checks_total: 1,
            checks_failing: 0,
        })
        ;(warehouseTablesChecksHealthRetrieve as jest.Mock).mockResolvedValue({
            health: 'unknown',
            checks_total: 0,
            checks_failing: 0,
        })
        ;(warehouseSavedQueriesCheckSuiteRunsList as jest.Mock).mockResolvedValue({ results: [] })
        ;(warehouseTablesCheckSuiteRunsList as jest.Mock).mockResolvedValue({ results: [] })
        ;(warehouseSavedQueriesChecksCheckTypesList as jest.Mock).mockResolvedValue(CHECK_TYPE_CATALOG)
    })

    afterEach(() => {
        jest.useRealTimers()
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it.each<[DataQualityChecksLogicProps, jest.Mock, jest.Mock]>([
        [VIEW_PROPS, warehouseSavedQueriesChecksList as jest.Mock, warehouseTablesChecksList as jest.Mock],
        [
            { subjectType: 'table', subjectId: 'table-1' },
            warehouseTablesChecksList as jest.Mock,
            warehouseSavedQueriesChecksList as jest.Mock,
        ],
    ])('routes requests to the %o subject family', async (props, expected, notExpected) => {
        await mountLogic(props)

        expect(expected).toHaveBeenCalledWith('1', props.subjectId, { limit: 100 })
        expect(notExpected).not.toHaveBeenCalled()
    })

    it('fails closed without a toast when the subject is forbidden', async () => {
        ;(warehouseSavedQueriesChecksList as jest.Mock).mockRejectedValue(forbidden())

        await mountLogic()

        expect(logic.values.accessDenied).toBe(true)
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it.each<[string, Record<string, unknown>, Record<string, unknown>]>([
        ['not_null', { checkType: 'not_null', columnName: 'customer_id' }, { column_name: 'customer_id', config: {} }],
        ['unique', { checkType: 'unique', columnName: 'customer_id' }, { column_name: 'customer_id', config: {} }],
        [
            'accepted_values',
            { checkType: 'accepted_values', columnName: 'status', acceptedValues: ['paid'] },
            { column_name: 'status', config: { values: ['paid'] } },
        ],
        [
            'relationships',
            {
                checkType: 'relationships',
                columnName: 'customer_id',
                toSubjectType: 'view',
                toSubjectUuid: 'view-2',
                toColumn: 'id',
            },
            {
                column_name: 'customer_id',
                config: { to_subject_type: 'view', to_subject_uuid: 'view-2', to_column: 'id' },
            },
        ],
        // row_count is the one type without a column, so column_name must be left out entirely.
        ['row_count', { checkType: 'row_count', rowCountMin: 1 }, { config: { min: 1 } }],
        [
            'freshness',
            { checkType: 'freshness', columnName: 'created_at', maxAgeMinutes: 60 },
            { column_name: 'created_at', config: { max_age_minutes: 60 } },
        ],
        ['custom_sql', { checkType: 'custom_sql', customSql: 'SELECT 1' }, { config: { query: 'SELECT 1' } }],
    ])('sends only the config %s needs', async (checkType, formValues, expectedBody) => {
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openFormWithCatalog(formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksCreate).toHaveBeenCalledWith('1', 'view-1', {
            check_type: checkType,
            severity: 'error',
            tags: [],
            ...expectedBody,
        })
    })

    it.each<[string, Record<string, unknown>]>([
        ['a name that is not an identifier', { checkType: 'not_null', columnName: 'id', name: '1_bad name' }],
        ['row_count bounds that cross', { checkType: 'row_count', rowCountMin: 10, rowCountMax: 1 }],
        ['a freshness window under a minute', { checkType: 'freshness', columnName: 'created_at', maxAgeMinutes: 0 }],
        ['a missing column', { checkType: 'not_null', columnName: '' }],
    ])('refuses to submit %s', async (_case, formValues) => {
        await mountLogic()
        await openFormWithCatalog(formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.checkModalOpen).toBe(true)
    })

    it('replaces the existing row when the server upserts instead of creating', async () => {
        // A semantically identical create returns the row that already exists, so appending it blindly
        // would show the same check twice.
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(
            buildCheck({ id: 'check-1', description: 'clarified' })
        )
        await mountLogic()
        await openFormWithCatalog({ checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checks.map((check) => check.id)).toEqual(['check-1'])
        expect(logic.values.checks[0].description).toEqual('clarified')
        expect(lemonToast.success).toHaveBeenCalledWith('Check saved', expect.anything())
    })

    it('leaves the assertion out of an edit, since the server rejects changing it', async () => {
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck({ name: 'renamed' }))
        await mountLogic()
        logic.actions.openCheckModal(buildCheck())
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ name: 'renamed' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksPartialUpdate).toHaveBeenCalledWith('1', 'view-1', 'check-1', {
            name: 'renamed',
            description: '',
            severity: 'error',
            tags: [],
        })
    })

    it('clears the name during an edit rather than dropping it', async () => {
        // A blank name is a supported "address by id" state, so the PATCH must carry the empty string
        // instead of omitting the key, which would leave the old name in place.
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck({ name: '' }))
        await mountLogic()
        logic.actions.openCheckModal(buildCheck({ name: 'existing_name' }))
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ name: '' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksPartialUpdate).toHaveBeenCalledWith('1', 'view-1', 'check-1', {
            name: '',
            description: '',
            severity: 'error',
            tags: [],
        })
    })

    it('creates the check once when the form is submitted twice', async () => {
        // Enter submits the form even while the save button is disabled by its loading state.
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openFormWithCatalog({ checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksCreate).toHaveBeenCalledTimes(1)
    })

    it('keeps the form open with the reason when the server rejects a create', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockRejectedValue(
            new ApiError('Forbidden', 403, undefined, { detail: "You don't have access to a table this check reads." })
        )
        await mountLogic()
        await openFormWithCatalog({ checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.serverError).toEqual("You don't have access to a table this check reads.")
        expect(logic.values.checkModalOpen).toBe(true)
        expect(logic.values.isCheckFormSubmitting).toBe(false)
    })

    it('drops the deleted row and refreshes health', async () => {
        ;(warehouseSavedQueriesChecksDestroy as jest.Mock).mockResolvedValue(undefined)
        await mountLogic()

        logic.actions.deleteCheck('check-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checks).toEqual([])
        expect(warehouseSavedQueriesChecksHealthRetrieve).toHaveBeenCalledTimes(2)
    })

    it('patches only the enabled flag when a check is toggled', async () => {
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck({ enabled: false }))
        await mountLogic()

        logic.actions.toggleCheckEnabled('check-1', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksPartialUpdate).toHaveBeenCalledWith('1', 'view-1', 'check-1', {
            enabled: false,
        })
        expect(logic.values.enabledChecksCount).toEqual(0)
    })

    it('skips polling and refreshes when a run comes back already finished', async () => {
        ;(warehouseSavedQueriesChecksRunCreate as jest.Mock).mockResolvedValue(
            buildSuiteRun({ status: 'completed', checks_passed: 2 })
        )
        await mountLogic()

        logic.actions.runCheck('check-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isSuiteRunning).toBe(false)
        expect(warehouseSavedQueriesCheckSuiteRunsRetrieve).not.toHaveBeenCalled()
        expect(warehouseSavedQueriesChecksList).toHaveBeenCalledTimes(2)
        // pluralize() joins the count to the noun with a non-breaking space.
        expect(lemonToast.success).toHaveBeenCalledWith('All 2\u00a0checks passed')
    })

    it('reloads the run history after completion when it was opened while empty', async () => {
        // History opened with no prior runs leaves suiteRuns empty, so length is a wrong proxy for
        // "opened". A finished run must still refresh the list rather than stay on "No runs yet".
        ;(warehouseSavedQueriesChecksRunCreate as jest.Mock).mockResolvedValue(
            buildSuiteRun({ status: 'completed', checks_passed: 1 })
        )
        await mountLogic()

        // The user expands the run history while it is still empty.
        logic.actions.loadSuiteRuns()
        await expectLogic(logic).toFinishAllListeners()
        ;(warehouseSavedQueriesCheckSuiteRunsList as jest.Mock).mockClear()

        logic.actions.runCheck('check-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesCheckSuiteRunsList).toHaveBeenCalledTimes(1)
    })

    it('says nothing ran when run all matches no enabled check', async () => {
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun({ status: 'empty' }))
        await mountLogic()

        logic.actions.runAll()
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.info).toHaveBeenCalledWith('No enabled checks to run')
        expect(logic.values.runAllInFlight).toBe(false)
    })

    it('reloads the checks once the polled run finishes', async () => {
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock)
            .mockResolvedValueOnce(buildSuiteRun())
            .mockResolvedValue(buildSuiteRun({ status: 'completed', checks_passed: 1, checks_failed: 1 }))
        await mountLogic()

        await startRunUnderFakeTimers()
        expect(logic.values.isSuiteRunning).toBe(true)

        await advancePoll(3000)
        await advancePoll(3000)

        expect(logic.values.isSuiteRunning).toBe(false)
        expect(lemonToast.warning).toHaveBeenCalledWith('1 passed, 1 failed')
    })

    it('ignores a stale poll after a newer run has replaced the active one', async () => {
        // A retrieve can still be in flight when a second run starts. The stale terminal response
        // must not finish the old run and dispose the newer run's poll.
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun({ id: 'suite-1' }))
        let resolveRetrieve: (run: DataQualitySuiteRunApi) => void = () => {}
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mockReturnValue(
            new Promise<DataQualitySuiteRunApi>((resolve) => {
                resolveRetrieve = resolve
            })
        )
        await mountLogic()

        await startRunUnderFakeTimers()
        // The first poll fires and its retrieve is now pending against suite-1.
        await advancePoll(3000)

        // A newer run replaces the active one while suite-1's retrieve is still in flight.
        logic.actions.setActiveSuiteRun(buildSuiteRun({ id: 'suite-2' }))
        await drainListeners()

        resolveRetrieve(buildSuiteRun({ id: 'suite-1', status: 'completed', checks_passed: 1 }))
        await drainListeners()

        expect(logic.values.activeSuiteRun?.id).toEqual('suite-2')
        expect(logic.values.isSuiteRunning).toBe(true)
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('ignores a suite start that resolves after a newer one', async () => {
        // Two starts can be in flight at once: the pending guard is per check, and "Run all" is not
        // blocked by it. A slower earlier request must not replace the run the panel is tracking.
        let resolveFirst: (run: DataQualitySuiteRunApi) => void = () => {}
        ;(warehouseSavedQueriesChecksRunCreate as jest.Mock)
            .mockReturnValueOnce(
                new Promise<DataQualitySuiteRunApi>((resolve) => {
                    resolveFirst = resolve
                })
            )
            .mockResolvedValueOnce(buildSuiteRun({ id: 'suite-second' }))
        await mountLogic()

        logic.actions.runCheck('check-1')
        logic.actions.runCheck('check-2')
        await drainListeners()
        expect(logic.values.activeSuiteRun?.id).toEqual('suite-second')

        resolveFirst(buildSuiteRun({ id: 'suite-first' }))
        await drainListeners()

        expect(logic.values.activeSuiteRun?.id).toEqual('suite-second')
    })

    it('reloads an expanded suite run detail once the run finishes', async () => {
        // A suite adopted mid-flight can be expanded while it is still running, caching partial rows.
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock)
            .mockResolvedValueOnce(buildSuiteRun())
            .mockResolvedValue(buildSuiteRun({ status: 'completed', checks_passed: 1 }))
        ;(warehouseSavedQueriesCheckSuiteRunsCheckRunsList as jest.Mock).mockResolvedValue([])
        await mountLogic()

        await startRunUnderFakeTimers()
        logic.actions.loadSuiteRunCheckRuns('suite-1')
        await drainListeners()
        const whileRunning = (warehouseSavedQueriesCheckSuiteRunsCheckRunsList as jest.Mock).mock.calls.length

        await advancePoll(3000)
        await advancePoll(3000)

        expect((warehouseSavedQueriesCheckSuiteRunsCheckRunsList as jest.Mock).mock.calls.length).toBeGreaterThan(
            whileRunning
        )
    })

    it('stops polling a run that never finishes', async () => {
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mockResolvedValue(buildSuiteRun())
        await mountLogic()

        await startRunUnderFakeTimers()

        // 3s cadence for the first minute, then 15s: 20 + 56 polls covers the 15 minute cap.
        for (let poll = 0; poll < 80 && !logic.values.pollTimedOut; poll++) {
            await advancePoll(poll < 20 ? 3000 : 15000)
        }

        expect(logic.values.pollTimedOut).toBe(true)
        expect(logic.values.isSuiteRunning).toBe(false)
        const pollsBeforeGivingUp = (warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length
        await advancePoll(15000)
        expect((warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length).toEqual(
            pollsBeforeGivingUp
        )
    })

    it('stops polling a run whose retrieve keeps failing', async () => {
        // A request that keeps rejecting (e.g. a 500 or the flag turned off mid-run) must still honor
        // the 15 minute cap instead of retrying forever and leaving the panel stuck running.
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mockRejectedValue(new Error('boom'))
        await mountLogic()

        await startRunUnderFakeTimers()

        // 3s cadence for the first minute, then 15s: 20 + 56 polls covers the 15 minute cap.
        for (let poll = 0; poll < 80 && !logic.values.pollTimedOut; poll++) {
            await advancePoll(poll < 20 ? 3000 : 15000)
        }

        expect(logic.values.pollTimedOut).toBe(true)
        expect(logic.values.isSuiteRunning).toBe(false)
        const pollsBeforeGivingUp = (warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length
        await advancePoll(15000)
        expect((warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length).toEqual(
            pollsBeforeGivingUp
        )
    })

    it('stops polling and denies access when a poll is forbidden', async () => {
        // A permanent 403 mid-run (flag off, or query access revoked) should take the access-denied
        // path at once rather than retrying until the 15 minute cap.
        ;(warehouseSavedQueriesChecksRunAllCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mockRejectedValue(forbidden())
        await mountLogic()

        await startRunUnderFakeTimers()
        await advancePoll(3000)

        expect(logic.values.accessDenied).toBe(true)
        const pollsBeforeDenied = (warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length
        await advancePoll(15000)
        expect((warehouseSavedQueriesCheckSuiteRunsRetrieve as jest.Mock).mock.calls.length).toEqual(pollsBeforeDenied)
    })

    it('adopts a run that was already in flight on mount', async () => {
        ;(warehouseSavedQueriesCheckSuiteRunsList as jest.Mock).mockResolvedValue({ results: [buildSuiteRun()] })

        await mountLogic()

        expect(warehouseSavedQueriesCheckSuiteRunsList).toHaveBeenCalledWith('1', 'view-1', { limit: 1 })
        expect(logic.values.isSuiteRunning).toBe(true)
    })

    // kea-test-utils waits on real timers, so the polling tests settle listeners by draining
    // microtasks instead: every step in the poll chain resolves an already-resolved mock.
    async function drainListeners(): Promise<void> {
        for (let tick = 0; tick < 20; tick++) {
            await Promise.resolve()
        }
    }

    async function startRunUnderFakeTimers(): Promise<void> {
        jest.useFakeTimers()
        logic.actions.runAll()
        await drainListeners()
    }

    async function advancePoll(ms: number): Promise<void> {
        jest.advanceTimersByTime(ms)
        await drainListeners()
    }
})

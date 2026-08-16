import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataQualityChecksHealthList,
    dataQualityChecksList,
    dataQualityRunsCreate,
    dataQualityRunsRetrieve,
} from 'products/data_quality/frontend/generated/api'
import type { DataQualityCheckApi, DataQualitySuiteRunApi } from 'products/data_quality/frontend/generated/api.schemas'

import { dataQualityOverviewLogic } from './dataQualityOverviewLogic'

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
}))

function buildCheck(id: string, subject: string, lastStatus: string | null): DataQualityCheckApi {
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
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([
            {
                subject_type: 'view',
                subject_uuid: 'uuid-orders',
                health: 'failing',
                checks_total: 2,
                checks_failing: 1,
            },
            {
                subject_type: 'view',
                subject_uuid: 'uuid-customers',
                health: 'healthy',
                checks_total: 1,
                checks_failing: 0,
            },
        ])
    })

    afterEach(() => {
        jest.useRealTimers()
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('keys subject health by uuid so two subjects can share a name', async () => {
        await mountLogic()

        expect(logic.values.healthBySubjectUuid['uuid-orders'].checks_failing).toEqual(1)
        expect(logic.values.failingSubjectCount).toEqual(1)
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

    it('opens only the subjects that need attention', async () => {
        await mountLogic()

        expect(logic.values.unhealthySubjectUuids).toEqual(['uuid-orders'])
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

    it('sends no ids when running everything', async () => {
        // An empty list is what the endpoint reads as "every enabled check", so it must not be
        // replaced by the currently filtered rows.
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(
            buildSuiteRun({ status: 'completed', checks_passed: 3 })
        )
        await mountLogic()
        logic.actions.setFilters({ status: 'failing' })

        logic.actions.runChecks()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityRunsCreate).toHaveBeenCalledWith('1', { check_ids: [] })
    })

    it('sends exactly one subject’s ids when running that subject', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(
            buildSuiteRun({ status: 'completed', checks_passed: 2 })
        )
        await mountLogic()

        logic.actions.runChecks(['check-1', 'check-2'])
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityRunsCreate).toHaveBeenCalledWith('1', { check_ids: ['check-1', 'check-2'] })
    })

    it('reloads the rows once the polled run finishes', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(dataQualityRunsRetrieve as jest.Mock)
            .mockResolvedValueOnce(buildSuiteRun())
            .mockResolvedValue(buildSuiteRun({ status: 'completed', checks_passed: 2, checks_failed: 1 }))
        await mountLogic()
        const loadsBeforeRun = (dataQualityChecksList as jest.Mock).mock.calls.length

        jest.useFakeTimers()
        logic.actions.runChecks()
        await drainListeners()
        expect(logic.values.isRunning).toBe(true)

        await advancePoll(3000)
        await advancePoll(3000)

        expect(logic.values.isRunning).toBe(false)
        expect((dataQualityChecksList as jest.Mock).mock.calls.length).toBeGreaterThan(loadsBeforeRun)
        expect(lemonToast.warning).toHaveBeenCalledWith('2 passed, 1 failed')
    })

    it('stops polling a run that never finishes', async () => {
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue(buildSuiteRun())
        ;(dataQualityRunsRetrieve as jest.Mock).mockResolvedValue(buildSuiteRun())
        await mountLogic()

        jest.useFakeTimers()
        logic.actions.runChecks()
        await drainListeners()

        for (let poll = 0; poll < 80 && !logic.values.pollTimedOut; poll++) {
            await advancePoll(poll < 20 ? 3000 : 15000)
        }

        expect(logic.values.pollTimedOut).toBe(true)
        expect(logic.values.isRunning).toBe(false)
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

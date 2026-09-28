import { checksApi, type DataQualitySubjectRef, type DataQualitySubjectType } from './checksApi'
import * as generated from './generated/api'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
    ApiError: class ApiError extends Error {},
}))

jest.mock('./generated/api')

interface Operation {
    name: string
    route: string
    call: (ref: DataQualitySubjectRef) => Promise<unknown>
    args: (subject: { subject_type: DataQualitySubjectType; subject_uuid: string }) => unknown[]
}

const SUBJECT_TYPES: DataQualitySubjectType[] = ['table', 'view', 'metric']

const mocked = generated as unknown as Record<string, jest.Mock>

describe('checksApi', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mocked.dataQualityChecksHealthList.mockResolvedValue([])
    })

    describe('subject-scoped operations', () => {
        const OPERATIONS: Operation[] = [
            {
                name: 'list',
                route: 'dataQualityChecksList',
                call: (ref) => checksApi.list(ref, 25),
                args: (subject) => [{ ...subject, limit: 25 }],
            },
            {
                name: 'create',
                route: 'dataQualityChecksCreate',
                call: (ref) => checksApi.create(ref, { check_type: 'not_null', column_name: 'id' }),
                args: (subject) => [{ check_type: 'not_null', column_name: 'id', ...subject }],
            },
            {
                name: 'runAll',
                route: 'dataQualityRunsCreate',
                call: (ref) => checksApi.runAll(ref),
                args: (subject) => [subject],
            },
            {
                name: 'checkTypes',
                route: 'dataQualityChecksCheckTypesList',
                call: (ref) => checksApi.checkTypes(ref),
                args: ({ subject_type }) => [{ subject_type }],
            },
            {
                name: 'health',
                route: 'dataQualityChecksHealthList',
                call: (ref) => checksApi.health(ref),
                args: (subject) => [subject],
            },
            {
                name: 'suiteRuns',
                route: 'dataQualityRunsList',
                call: (ref) => checksApi.suiteRuns(ref, 25),
                args: (subject) => [{ ...subject, limit: 25 }],
            },
            {
                name: 'schedule',
                route: 'dataQualityChecksScheduleRetrieve',
                call: (ref) => checksApi.schedule(ref),
                args: (subject) => [subject],
            },
            {
                name: 'updateSchedule',
                route: 'dataQualityChecksSchedulePartialUpdate',
                call: (ref) => checksApi.updateSchedule(ref, { interval: '24hour' }),
                args: (subject) => [{ interval: '24hour', ...subject }],
            },
        ]

        test.each(
            SUBJECT_TYPES.flatMap((subjectType) =>
                OPERATIONS.map((operation) => [subjectType, operation.name, operation] as const)
            )
        )('names the subject of a %s %s in the request', async (subjectType, _name, operation) => {
            await operation.call({ subjectType, subjectId: 'subject-1' })

            const expected = operation.args({ subject_type: subjectType, subject_uuid: 'subject-1' })
            expect(mocked[operation.route]).toHaveBeenCalledWith('1', ...expected)
        })
    })

    it('reads the output schema only for a metric', async () => {
        expect(await checksApi.outputSchema({ subjectType: 'table', subjectId: 'subject-1' })).toEqual({ columns: [] })
        expect(mocked.dataQualityChecksOutputSchemaRetrieve).not.toHaveBeenCalled()

        await checksApi.outputSchema({ subjectType: 'metric', subjectId: 'subject-1' })
        expect(mocked.dataQualityChecksOutputSchemaRetrieve).toHaveBeenCalledWith('1', {
            subject_type: 'metric',
            subject_uuid: 'subject-1',
        })
    })

    it('reports a subject with no rollup as unknown rather than missing', async () => {
        expect(await checksApi.health({ subjectType: 'view', subjectId: 'subject-1' })).toEqual({
            subject_type: 'view',
            subject_uuid: 'subject-1',
            health: 'unknown',
            checks_total: 0,
            checks_failing: 0,
        })
    })

    it('addresses a check by id alone, without its subject', async () => {
        await checksApi.partialUpdate('check-1', { enabled: false })
        await checksApi.destroy('check-1')
        await checksApi.run('check-1')
        await checksApi.runs('check-1')
        await checksApi.suiteRunRetrieve('suite-1')
        await checksApi.suiteRunCheckRuns('suite-1')

        expect(mocked.dataQualityChecksPartialUpdate).toHaveBeenCalledWith('1', 'check-1', { enabled: false })
        expect(mocked.dataQualityChecksDestroy).toHaveBeenCalledWith('1', 'check-1')
        expect(mocked.dataQualityChecksRunCreate).toHaveBeenCalledWith('1', 'check-1')
        expect(mocked.dataQualityChecksRunsList).toHaveBeenCalledWith('1', 'check-1')
        expect(mocked.dataQualityRunsRetrieve).toHaveBeenCalledWith('1', 'suite-1')
        expect(mocked.dataQualityRunsCheckRunsList).toHaveBeenCalledWith('1', 'suite-1')
    })
})

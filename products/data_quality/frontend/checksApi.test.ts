import { checksApi, type DataQualitySubjectRef, type DataQualitySubjectType } from './checksApi'
import * as generated from './generated/api'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
    ApiError: class ApiError extends Error {},
}))

jest.mock('./generated/api')

const ROUTE_PREFIX: Record<DataQualitySubjectType, string> = {
    table: 'warehouseTables',
    view: 'warehouseSavedQueries',
    metric: 'dataCatalogMetrics',
}

interface Operation {
    name: string
    route: string
    call: (ref: DataQualitySubjectRef) => Promise<unknown>
    trailingArgs: unknown[]
}

const OPERATIONS: Operation[] = [
    { name: 'list', route: 'ChecksList', call: (ref) => checksApi.list(ref, 25), trailingArgs: [{ limit: 25 }] },
    {
        name: 'create',
        route: 'ChecksCreate',
        call: (ref) => checksApi.create(ref, { check_type: 'not_null', column_name: 'id' }),
        trailingArgs: [{ check_type: 'not_null', column_name: 'id' }],
    },
    {
        name: 'partialUpdate',
        route: 'ChecksPartialUpdate',
        call: (ref) => checksApi.partialUpdate(ref, 'check-1', { enabled: false }),
        trailingArgs: ['check-1', { enabled: false }],
    },
    {
        name: 'destroy',
        route: 'ChecksDestroy',
        call: (ref) => checksApi.destroy(ref, 'check-1'),
        trailingArgs: ['check-1'],
    },
    { name: 'run', route: 'ChecksRunCreate', call: (ref) => checksApi.run(ref, 'check-1'), trailingArgs: ['check-1'] },
    { name: 'runAll', route: 'ChecksRunAllCreate', call: (ref) => checksApi.runAll(ref), trailingArgs: [] },
    { name: 'runs', route: 'ChecksRunsList', call: (ref) => checksApi.runs(ref, 'check-1'), trailingArgs: ['check-1'] },
    {
        name: 'checkTypes',
        route: 'ChecksCheckTypesList',
        call: (ref) => checksApi.checkTypes(ref),
        trailingArgs: [],
    },
    { name: 'health', route: 'ChecksHealthRetrieve', call: (ref) => checksApi.health(ref), trailingArgs: [] },
    {
        name: 'suiteRuns',
        route: 'CheckSuiteRunsList',
        call: (ref) => checksApi.suiteRuns(ref, 25),
        trailingArgs: [{ limit: 25 }],
    },
    {
        name: 'suiteRunRetrieve',
        route: 'CheckSuiteRunsRetrieve',
        call: (ref) => checksApi.suiteRunRetrieve(ref, 'suite-1'),
        trailingArgs: ['suite-1'],
    },
    {
        name: 'suiteRunCheckRuns',
        route: 'CheckSuiteRunsCheckRunsList',
        call: (ref) => checksApi.suiteRunCheckRuns(ref, 'suite-1'),
        trailingArgs: ['suite-1'],
    },
]

const SUBJECT_TYPES: DataQualitySubjectType[] = ['table', 'view', 'metric']

const mocked = generated as unknown as Record<string, jest.Mock>

describe('checksApi', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    test.each(
        SUBJECT_TYPES.flatMap((subjectType) =>
            OPERATIONS.map((operation) => [subjectType, operation.name, operation] as const)
        )
    )('sends a %s %s to its own endpoint', async (subjectType, _name, operation) => {
        const expected = `${ROUTE_PREFIX[subjectType]}${operation.route}`

        await operation.call({ subjectType, subjectId: 'subject-1' })

        expect(mocked[expected]).toHaveBeenCalledWith('1', 'subject-1', ...operation.trailingArgs)
    })
})

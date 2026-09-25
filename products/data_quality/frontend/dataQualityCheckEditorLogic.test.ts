import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { DataQualitySubjectRef } from './checksApi'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import {
    dataQualityChecksCheckTypesList,
    dataQualityChecksCreate,
    dataQualityChecksSubjectsList,
    dataQualityChecksOutputSchemaRetrieve,
    dataQualityChecksPartialUpdate,
} from './generated/api'
import type { DataQualityCheckApi } from './generated/api.schemas'
import { CheckTypeEnumApi } from './generated/api.schemas'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        code: string | null
        attr: string | null
        constructor(
            message?: string,
            status?: number,
            _headers?: unknown,
            data?: { detail?: string; code?: string; attr?: string }
        ) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
            this.code = data?.code ?? null
            this.attr = data?.attr ?? null
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

jest.mock('lib/lemon-ui/LemonDialog', () => ({
    LemonDialog: { open: jest.fn() },
}))

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('./generated/api', () => ({
    dataQualityChecksCheckTypesList: jest.fn(),
    dataQualityChecksCreate: jest.fn(),
    dataQualityChecksSubjectsList: jest.fn(),
    dataQualityChecksOutputSchemaRetrieve: jest.fn(),
    dataQualityChecksPartialUpdate: jest.fn(),
}))

const VIEW_SUBJECT: DataQualitySubjectRef = { subjectType: 'view', subjectId: 'view-1' }
const COLUMNS = ['customer_id', 'status', 'created_at', 'total']

const SUBJECT_CATALOG = [
    {
        subject_type: 'view',
        id: 'view-7',
        name: 'orders_view',
        display_name: '',
        time_column: '',
        columns: { order_id: 'string' },
        editable: true,
    },
    {
        subject_type: 'table',
        id: 'table-9',
        name: 'stripe_charges',
        display_name: '',
        time_column: '',
        columns: { customer_id: 'string', amount: 'decimal' },
        editable: false,
    },
    {
        subject_type: 'metric',
        id: 'metric-1',
        name: 'daily_signups',
        display_name: 'Daily signups',
        time_column: '',
        columns: {},
        editable: true,
    },
    {
        subject_type: 'posthog_table',
        id: 'events-1',
        name: 'events',
        display_name: '',
        time_column: 'timestamp',
        columns: { distinct_id: 'string', timestamp: 'datetime' },
        editable: true,
    },
]

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
        name: '',
        description: '',
        enabled: true,
        severity: 'error',
        last_status: '',
        config: {},
        tags: [],
        ...overrides,
    } as DataQualityCheckApi
}

function apiError(data: { detail?: string; code?: string; attr?: string }, status = 400): Error {
    const { ApiError } = jest.requireMock('lib/api')
    return new ApiError(data.detail, status, undefined, data)
}

describe('dataQualityCheckEditorLogic', () => {
    let logic: ReturnType<typeof dataQualityCheckEditorLogic.build>
    const onSaved = jest.fn()
    const onRunNow = jest.fn()
    const onClosed = jest.fn()

    async function mountLogic(
        overrides: Partial<DataQualityCheckEditorLogicProps> = {}
    ): Promise<ReturnType<typeof dataQualityCheckEditorLogic.build>> {
        initKeaTests()
        logic = dataQualityCheckEditorLogic({ surface: 'subject', onSaved, onRunNow, onClosed, ...overrides })
        logic.mount()
        return logic
    }

    async function openWith(
        check: DataQualityCheckApi | null,
        values: Record<string, unknown> = {},
        columns: string[] = COLUMNS
    ): Promise<void> {
        logic.actions.openEditor(check, VIEW_SUBJECT, columns)
        await expectLogic(logic).toFinishAllListeners()
        if (Object.keys(values).length) {
            logic.actions.setCheckFormValues(values)
            await expectLogic(logic).toFinishAllListeners()
        }
    }

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(CHECK_TYPE_CATALOG)
        ;(dataQualityChecksSubjectsList as jest.Mock).mockResolvedValue(SUBJECT_CATALOG)
        ;(dataQualityChecksOutputSchemaRetrieve as jest.Mock).mockResolvedValue({
            columns: [
                { name: 'day', type: 'Nullable(Date)' },
                { name: 'signups', type: 'UInt64' },
            ],
        })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('authors metric SQL with a relation placeholder, no column, and no raw query execution', async () => {
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(
            CHECK_TYPE_CATALOG.filter((type) => type.check_type === 'custom_sql')
        )
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ check_type: 'custom_sql' }))
        await mountLogic()
        logic.actions.openEditor(null, { subjectType: 'metric', subjectId: 'metric-1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.checkForm).toMatchObject({
            checkType: 'custom_sql',
            columnName: '',
            customSql: 'SELECT *\nFROM {metric}\nWHERE <failure condition>',
        })
        expect(logic.values.checkTypes.map((type) => type.check_type)).toEqual(['custom_sql'])
        expect(logic.values.requiresColumn).toBe(false)
        expect(logic.values.needsSubjectCatalog).toBe(false)
        expect(logic.values.isMetricSubject).toBe(true)
        expect(logic.values.availableOutputSchema).toEqual([
            { name: 'day', type: 'Nullable(Date)' },
            { name: 'signups', type: 'UInt64' },
        ])
        logic.actions.setCheckFormValue('customSql', 'SELECT * FROM {metric} WHERE signups < 100')
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()
        expect(dataQualityChecksCreate).toHaveBeenCalledWith(
            '1',
            expect.objectContaining({
                subject_type: 'metric',
                subject_uuid: 'metric-1',
                check_type: 'custom_sql',
                column_name: '',
                config: { query: 'SELECT * FROM {metric} WHERE signups < 100' },
            })
        )
        expect(performQuery).not.toHaveBeenCalled()
    })

    it('offers HogQL metrics in the overview and pre-fills the metric query after selection', async () => {
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(
            CHECK_TYPE_CATALOG.filter((type) => type.check_type === 'custom_sql')
        )
        await mountLogic({ surface: 'overview' })

        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectableSubjects).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    id: 'metric-1',
                    name: 'Daily signups',
                    type: 'metric',
                }),
            ])
        )

        logic.actions.setSubject({ subjectType: 'metric', subjectId: 'metric-1' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkForm).toMatchObject({
            checkType: 'custom_sql',
            customSql: 'SELECT *\nFROM {metric}\nWHERE <failure condition>',
        })
        expect(dataQualityChecksOutputSchemaRetrieve).toHaveBeenCalledWith('1', {
            subject_type: 'metric',
            subject_uuid: 'metric-1',
        })
    })

    it('uses warehouse field types as the selected table output schema', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSubject({ subjectType: 'table', subjectId: 'table-9' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.availableOutputSchema).toEqual([
            { name: 'customer_id', type: 'string' },
            { name: 'amount', type: 'decimal' },
        ])
    })

    it('does not let a late table catalog replace the metric-only check types', async () => {
        let resolveTableCatalog: (catalog: typeof CHECK_TYPE_CATALOG) => void = () => {}
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveTableCatalog = resolve
            })
        )
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(
            CHECK_TYPE_CATALOG.filter((type) => type.check_type === 'custom_sql')
        )
        await mountLogic()
        logic.actions.openEditor(null, { subjectType: 'table', subjectId: 'table-1' }, COLUMNS)
        logic.actions.openEditor(null, { subjectType: 'metric', subjectId: 'metric-1' })
        await expectLogic(logic).toDispatchActions(['loadCheckTypesSuccess'])
        resolveTableCatalog(CHECK_TYPE_CATALOG)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.checkTypes.map((type) => type.check_type)).toEqual(['custom_sql'])
    })

    it('discards an in-flight table preview when opening a metric check', async () => {
        let resolvePreview: (response: { columns: string[]; results: unknown[][] }) => void = () => {}
        ;(performQuery as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolvePreview = resolve
            })
        )
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(
            CHECK_TYPE_CATALOG.filter((type) => type.check_type === 'custom_sql')
        )
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT 1' })
        logic.actions.runCustomSqlPreview(undefined)
        logic.actions.openEditor(null, { subjectType: 'metric', subjectId: 'metric-1' })
        resolvePreview({ columns: ['value'], results: [[1]] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.customSqlPreview).toBeNull()
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
        // row_count is the one type without a column, so column_name goes out blank.
        ['row_count', { checkType: 'row_count', rowCountMin: 1 }, { column_name: '', config: { min: 1 } }],
        [
            'freshness',
            { checkType: 'freshness', columnName: 'created_at', maxAgeMinutes: 60 },
            { column_name: 'created_at', config: { max_age_minutes: 60 } },
        ],
        [
            'custom_sql',
            { checkType: 'custom_sql', customSql: 'SELECT 1' },
            { column_name: '', config: { query: 'SELECT 1' } },
        ],
    ])('sends only the config %s needs', async (checkType, formValues, expectedBody) => {
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openWith(null, formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).toHaveBeenCalledWith('1', {
            check_type: checkType,
            severity: 'error',
            tags: [],
            ...expectedBody,
            subject_type: 'view',
            subject_uuid: 'view-1',
        })
    })

    it('sends the whole definition when an assertion is edited', async () => {
        // The old check kept its assertion; an edit now has to carry type, column and config together
        // so switching type cannot leave the previous type's config behind.
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(buildCheck({ name: 'orders_not_null', description: 'why' }), {
            checkType: 'accepted_values',
            columnName: 'status',
            acceptedValues: ['paid'],
        })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksPartialUpdate).toHaveBeenCalledWith('1', 'check-1', {
            check_type: 'accepted_values',
            column_name: 'status',
            config: { values: ['paid'] },
            severity: 'error',
            name: 'orders_not_null',
            description: 'why',
            tags: [],
        })
    })

    it('leaves an unchanged assertion out of a metadata-only edit', async () => {
        // The backend revalidates the definition whenever a request carries one, which a metric that
        // moved off its HogQL definition fails. Renaming its check must not go down that path.
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockResolvedValue(
            CHECK_TYPE_CATALOG.filter((type) => type.check_type === 'custom_sql')
        )
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        logic.actions.openEditor(
            buildCheck({
                check_type: CheckTypeEnumApi.CustomSql,
                column_name: '',
                config: { query: 'SELECT 1 FROM {metric}' },
                name: 'signup_floor',
            }),
            { subjectType: 'metric', subjectId: 'metric-1' }
        )
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ name: 'signups_floor', description: 'renamed' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksPartialUpdate).toHaveBeenCalledWith('1', 'check-1', {
            severity: 'error',
            name: 'signups_floor',
            description: 'renamed',
            tags: [],
        })
    })

    it.each<[string, Partial<DataQualityCheckApi>]>([
        [
            'a relationships check with no target window',
            {
                check_type: CheckTypeEnumApi.Relationships,
                config: {
                    to_subject_type: 'table',
                    to_subject_uuid: 'table-9',
                    to_column: 'customer_id',
                    to_lookback_hours: null,
                },
            },
        ],
        [
            'a row_count check with only a minimum',
            { check_type: CheckTypeEnumApi.RowCount, column_name: '', config: { min: 10, max: null } },
        ],
    ])('leaves the assertion out of a metadata-only edit of %s', async (_case, storedCheck) => {
        // The stored config writes an unset value as null, so a comparison that counts keys reads
        // every rename as an assertion edit and sends a definition the backend then revalidates.
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(buildCheck(storedCheck), { description: 'renamed' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksPartialUpdate).toHaveBeenCalledWith('1', 'check-1', {
            severity: 'error',
            name: '',
            description: 'renamed',
            tags: [],
        })
    })

    it('does not submit before the check-type catalog arrives', async () => {
        // Enter can submit while the catalog request is still pending. Without it there is no column
        // requirement to validate against, so the payload would omit column_name and be rejected.
        ;(dataQualityChecksCheckTypesList as jest.Mock).mockReturnValueOnce(new Promise(() => {}))
        await mountLogic()
        logic.actions.openEditor(null, VIEW_SUBJECT, COLUMNS)

        // Not toFinishAllListeners: the catalog request never settles, which is the point.
        logic.actions.submitCheckForm()
        for (let tick = 0; tick < 20; tick++) {
            await Promise.resolve()
        }

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
    })

    it('sends blank metadata on an edit so it can be cleared', async () => {
        // Create omits blank optional fields, which would leave an edit unable to remove a name.
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(buildCheck({ name: 'orders_not_null', description: 'why', tags: ['core'] }), {
            name: '',
            description: '',
            tags: [],
        })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksPartialUpdate).toHaveBeenCalledWith(
            '1',
            'check-1',
            expect.objectContaining({ name: '', description: '', tags: [] })
        )
    })

    it.each<[string, Record<string, unknown>]>([
        ['a name that is not an identifier', { checkType: 'not_null', columnName: 'id', name: '1_bad name' }],
        ['row_count bounds that cross', { checkType: 'row_count', rowCountMin: 10, rowCountMax: 1 }],
        ['a freshness window under a minute', { checkType: 'freshness', columnName: 'created_at', maxAgeMinutes: 0 }],
        ['a missing column', { checkType: 'not_null', columnName: '' }],
    ])('refuses to submit %s', async (_case, formValues) => {
        await mountLogic()
        await openWith(null, formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.isOpen).toBe(true)
    })

    it.each<[string, Record<string, unknown>, 'lookbackHours' | 'toLookbackHours']>([
        [
            'a window of zero hours',
            { checkType: 'not_null', columnName: 'customer_id', lookbackHours: 0 },
            'lookbackHours',
        ],
        [
            'a window of half an hour',
            { checkType: 'not_null', columnName: 'customer_id', lookbackHours: 0.5 },
            'lookbackHours',
        ],
        [
            'a target window of zero hours',
            {
                checkType: 'relationships',
                columnName: 'customer_id',
                toSubjectUuid: 'table-9',
                toColumn: 'customer_id',
                toLookbackHours: 0,
            },
            'toLookbackHours',
        ],
    ])('refuses to submit %s and says so beside that window', async (_case, formValues, field) => {
        await mountLogic()
        await openWith(null, formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.checkFormErrors[field as 'name']).toEqual('Set a whole number of hours, at least one.')
    })

    it('reads a cleared window as no window rather than a bad one', async () => {
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        // What the number input emits once its content is deleted.
        await openWith(null, { checkType: 'not_null', columnName: 'customer_id', lookbackHours: NaN })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkFormErrors.lookbackHours).toBeUndefined()
        expect(dataQualityChecksCreate).toHaveBeenCalledWith('1', expect.objectContaining({ config: {} }))
    })

    it('creates the check once when the form is submitted twice', async () => {
        // Enter submits the form even while the save button is disabled by its loading state.
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openWith(null, { checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).toHaveBeenCalledTimes(1)
    })

    it('shows a stale failing preview until the custom SQL is tested again', async () => {
        ;(performQuery as jest.Mock).mockResolvedValue({
            columns: ['order_id'],
            results: [['order-1']],
            hasMore: false,
        })
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT order_id FROM orders' })

        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined))
            .toDispatchActions(['runCustomSqlPreviewSuccess'])
            .toFinishAllListeners()

        expect(logic.values.customSqlPreviewVerdict).toEqual('fail')
        expect(logic.values.customSqlPreviewStale).toBe(false)

        logic.actions.setCheckFormValue('customSql', "SELECT order_id FROM orders WHERE status = 'failed'")

        expect(logic.values.customSqlPreviewStale).toBe(true)

        ;(performQuery as jest.Mock).mockResolvedValueOnce({ columns: [], results: [], hasMore: false })
        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined))
            .toDispatchActions(['runCustomSqlPreviewSuccess'])
            .toFinishAllListeners()

        expect(logic.values.customSqlPreviewVerdict).toEqual('pass')
        expect(logic.values.customSqlPreviewStale).toBe(false)
    })

    it('forces a fresh calculation for the custom SQL preview so it cannot serve cached data', async () => {
        ;(performQuery as jest.Mock).mockResolvedValue({ columns: [], results: [], hasMore: false })
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT order_id FROM orders' })

        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined))
            .toDispatchActions(['runCustomSqlPreviewSuccess'])
            .toFinishAllListeners()

        const refresh = (performQuery as jest.Mock).mock.calls.at(-1)?.[2]
        expect(refresh).toEqual('force_blocking')
    })

    it('carries warehouse-sync warnings onto the preview so a pass is not shown as final', async () => {
        // A query over a source whose last sync failed can still return zero rows, which would
        // otherwise read as a confident pass over data the platform already knows is behind.
        ;(performQuery as jest.Mock).mockResolvedValue({
            columns: [],
            results: [],
            hasMore: false,
            warnings: [
                {
                    type: 'warehouse_sync',
                    table_name: 'stripe_charges',
                    schema_name: 'charges',
                    source_type: 'Stripe',
                    status: 'Failed',
                    message: 'The Stripe charges sync last failed, so this data may be behind.',
                },
            ],
        })
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT id FROM stripe_charges WHERE amount < 0' })

        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined))
            .toDispatchActions(['runCustomSqlPreviewSuccess'])
            .toFinishAllListeners()

        expect(logic.values.customSqlPreviewVerdict).toEqual('pass')
        expect(logic.values.customSqlPreview?.warnings).toEqual([
            expect.objectContaining({
                type: 'warehouse_sync',
                message: 'The Stripe charges sync last failed, so this data may be behind.',
            }),
        ])
    })

    it('clears a custom SQL preview error when the query changes', async () => {
        ;(performQuery as jest.Mock).mockRejectedValue({ detail: 'Unknown table' })
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT * FROM missing' })

        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined))
            .toDispatchActions(['runCustomSqlPreviewFailure'])
            .toFinishAllListeners()

        expect(logic.values.customSqlPreviewError).toEqual('Unknown table')

        logic.actions.setCheckFormValue('customSql', 'SELECT 1')

        expect(logic.values.customSqlPreviewError).toBeNull()
    })

    it('drops a superseded preview so a late failure keeps the newer result', async () => {
        // Cmd+Enter can start a second preview while the first is still running. If the older
        // request then fails, its error must not replace the newer request's good result.
        let failFirst: (error: unknown) => void = () => {}
        ;(performQuery as jest.Mock)
            .mockImplementationOnce(() => new Promise((_resolve, reject) => (failFirst = reject)))
            .mockResolvedValueOnce({ columns: [], results: [], hasMore: false })

        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT order_id FROM orders' })

        // First request stays pending; the second supersedes it and passes. Do not wait for all
        // listeners here — the first request is meant to still be in flight.
        logic.actions.runCustomSqlPreview(undefined)
        await expectLogic(logic, () => logic.actions.runCustomSqlPreview(undefined)).toDispatchActions([
            'runCustomSqlPreviewSuccess',
        ])

        expect(logic.values.customSqlPreviewVerdict).toEqual('pass')

        // The stale first request fails last; the breakpoint must swallow it, not show an error.
        failFirst({ detail: 'Unknown table' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.customSqlPreviewError).toBeNull()
        expect(logic.values.customSqlPreviewVerdict).toEqual('pass')
    })

    it('blocks saving custom SQL with a Monaco validation error', async () => {
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT * FROM orders' })

        logic.actions.setCustomSqlEditorError('Unknown table')
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.checkFormErrors.customSql).toEqual('Unknown table')
    })

    it('blocks saving custom SQL until Monaco validates an edited query', async () => {
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT * FROM orders' })

        logic.actions.setCheckFormValue('customSql', 'SELECT * FROM orders WHERE missing_column = 1')
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.checkFormErrors.customSql).toEqual('Checking query...')
    })

    it('saves a query nobody edited while Monaco validates the one it opened with', async () => {
        // Monaco validates the query as soon as the editor mounts. That pass is not an edit, so it
        // must not hold the save while it runs.
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(
            buildCheck({
                check_type: CheckTypeEnumApi.CustomSql,
                column_name: '',
                config: { query: 'SELECT id FROM orders' },
            }),
            { description: 'Every order keeps a positive id' }
        )

        logic.actions.setCustomSqlValidationLoading(true)
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksPartialUpdate).toHaveBeenCalledWith(
            '1',
            'check-1',
            expect.objectContaining({ description: 'Every order keeps a positive id' })
        )
    })

    it('keeps a Monaco error until an edited query receives a new validation result', async () => {
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT * FROM orders' })

        logic.actions.setCustomSqlEditorError('Error on line 1, column 15')
        logic.actions.setCheckFormValue('customSql', 'SELECT * FROM orderz')

        expect(logic.values.customSqlEditorError).toEqual('Error on line 1, column 15')
    })

    it.each<[string, { detail: string; code?: string; attr?: string }, string, string]>([
        [
            'a taken name beside the name field',
            { detail: 'A check with this name already exists.', attr: 'name', code: 'name_conflict' },
            'name',
            'A check with this name already exists.',
        ],
        [
            'an unusable config beside the config field',
            { detail: 'Invalid config for a custom_sql check.', attr: 'config' },
            'customSql',
            'Invalid config for a custom_sql check.',
        ],
        [
            'a duplicate definition beside every assertion field',
            {
                detail: 'A check with this definition already exists.',
                attr: 'config',
                code: 'duplicate_definition',
            },
            'checkType',
            'A check with this definition already exists.',
        ],
    ])('keeps the draft open and shows %s', async (_case, data, field, message) => {
        ;(dataQualityChecksCreate as jest.Mock).mockRejectedValue(apiError(data))
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT 1' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkFormErrors[field as 'name']).toEqual(message)
        expect(logic.values.serverError).toBeNull()
        expect(logic.values.isOpen).toBe(true)
    })

    it('shows a failure with no field of its own in the modal banner', async () => {
        ;(dataQualityChecksCreate as jest.Mock).mockRejectedValue(
            apiError({ detail: 'nope', code: 'permission_denied' }, 403)
        )
        await mountLogic()
        await openWith(null, { checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.serverError).toEqual("You don't have access to all data referenced by this check.")
        expect(logic.values.isOpen).toBe(true)
    })

    it('hands the saved check to the surface that opened it, and offers to run it', async () => {
        const saved = buildCheck({ id: 'check-new' })
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(saved)
        await mountLogic()
        await openWith(null, { checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(onSaved).toHaveBeenCalledWith(saved)
        expect(logic.values.isOpen).toBe(false)
        const toast = (lemonToast.success as jest.Mock).mock.calls[0]
        expect(toast[0]).toEqual('Check saved')
        toast[1].button.action()
        expect(onRunNow).toHaveBeenCalledWith(saved)
    })

    it("names the check's own subject, not the surface it was opened from", async () => {
        // The overview edits checks on every table and view, so the subject travels with the check.
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, { subjectType: 'table', subjectId: 'table-9' }, COLUMNS)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).toHaveBeenCalledWith(
            '1',
            expect.objectContaining({ subject_type: 'table', subject_uuid: 'table-9' })
        )
    })

    it.each<[string, DataQualitySubjectRef, string]>([
        ['a table', { subjectType: 'table', subjectId: 'table-9' }, 'customer_id'],
        ['a view', { subjectType: 'view', subjectId: 'view-7' }, 'order_id'],
    ])('opens without a subject and creates against %s after it is picked', async (_case, subject, column) => {
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic({ surface: 'overview' })

        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCheckTypesList).not.toHaveBeenCalled()
        expect((dataQualityChecksSubjectsList as jest.Mock).mock.calls.length).toEqual(1)

        logic.actions.setSubject(subject)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: column })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).toHaveBeenCalledWith(
            '1',
            expect.objectContaining({
                column_name: column,
                subject_type: subject.subjectType,
                subject_uuid: subject.subjectId,
            })
        )
    })

    it('clears subject-specific errors and columns when the picked subject changes', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSubject({ subjectType: 'table', subjectId: 'table-9' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ columnName: 'customer_id', toColumn: 'id' })
        logic.actions.setCheckFormManualErrors({ columnName: 'Pick a column.' })
        logic.actions.setServerError('Could not save the check.')

        logic.actions.setSubject({ subjectType: 'view', subjectId: 'view-7' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkForm.columnName).toEqual('')
        expect(logic.values.checkForm.toColumn).toEqual('')
        expect(logic.values.checkFormManualErrors).toEqual({})
        expect(logic.values.serverError).toBeNull()
    })

    it('reloads check types when the picked subject changes', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSubject({ subjectType: 'table', subjectId: 'table-9' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSubject({ subjectType: 'view', subjectId: 'view-7' })
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCheckTypesList).toHaveBeenCalledWith('1', { subject_type: 'table' })
        expect(dataQualityChecksCheckTypesList).toHaveBeenCalledWith('1', { subject_type: 'view' })
    })

    it('does not create a check until a subject is picked', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).not.toHaveBeenCalled()
    })

    it('clears the check type error when a failed catalog request is retried', async () => {
        ;(dataQualityChecksCheckTypesList as jest.Mock)
            .mockRejectedValueOnce(new Error('down'))
            .mockResolvedValueOnce(CHECK_TYPE_CATALOG)
        await mountLogic()
        logic.actions.openEditor(null, VIEW_SUBJECT, COLUMNS)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkTypesError).toBe(true)

        logic.actions.loadCheckTypes()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkTypesError).toBe(false)
        expect(logic.values.checkTypes).toEqual(CHECK_TYPE_CATALOG)
    })

    it('drops a superseded check type request so a late failure keeps the newer catalog', async () => {
        let failFirst: (error: unknown) => void = () => {}
        ;(dataQualityChecksCheckTypesList as jest.Mock)
            .mockImplementationOnce(() => new Promise((_resolve, reject) => (failFirst = reject)))
            .mockResolvedValueOnce(CHECK_TYPE_CATALOG)
        await mountLogic()

        // The first request stays in flight while a subject change supersedes it.
        logic.actions.openEditor(null, VIEW_SUBJECT, COLUMNS)
        await expectLogic(logic, () =>
            logic.actions.setSubject({ subjectType: 'view', subjectId: 'view-2' })
        ).toDispatchActions(['loadCheckTypesSuccess'])

        failFirst(new Error('down'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkTypesError).toBe(false)
        expect(logic.values.checkTypes).toEqual(CHECK_TYPE_CATALOG)
    })

    it('closes an untouched draft without asking', async () => {
        await mountLogic()
        await openWith(buildCheck())

        logic.actions.requestClose()
        await expectLogic(logic).toFinishAllListeners()

        expect(LemonDialog.open).not.toHaveBeenCalled()
        expect(logic.values.isOpen).toBe(false)
        expect(onClosed).toHaveBeenCalled()
    })

    it('asks before dropping an edited draft, and closes only on discard', async () => {
        await mountLogic()
        await openWith(buildCheck(), { description: 'half written' })

        logic.actions.requestClose()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(true)
        const dialog = (LemonDialog.open as jest.Mock).mock.calls[0][0]
        expect(dialog.title).toEqual('Discard changes?')
        dialog.primaryButton.onClick()
        expect(logic.values.isOpen).toBe(false)
    })

    it('closes a saved draft without asking, since it is no longer unsaved', async () => {
        ;(dataQualityChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck({ description: 'written' }))
        await mountLogic()
        await openWith(buildCheck(), { description: 'written' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(LemonDialog.open).not.toHaveBeenCalled()
        expect(logic.values.checkFormChanged).toBe(false)
    })

    it('offers every editable subject as a parent and a read-only one only as a target', async () => {
        await mountLogic({ surface: 'overview' })

        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectableSubjects).toEqual([
            { id: 'view-7', name: 'orders_view', type: 'view' },
            { id: 'metric-1', name: 'Daily signups', type: 'metric' },
            { id: 'events-1', name: 'events', type: 'posthog_table' },
        ])
        expect(logic.values.relationshipSubjects.map((subject) => subject.id)).toEqual([
            'view-7',
            'table-9',
            'events-1',
        ])
    })

    it.each<[Record<string, unknown>, string | null]>([
        [{ subjectType: 'posthog_table', subjectId: 'events-1' }, 'timestamp'],
        [{ subjectType: 'table', subjectId: 'table-9' }, null],
    ])('offers a lookback window only for a subject with a time column (%o)', async (subject, expected) => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSubject(subject as never)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.subjectTimeColumn).toEqual(expected)
    })

    it('sends the window it was given, and drops it for custom SQL', async () => {
        ;(dataQualityChecksCreate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSubject({ subjectType: 'posthog_table', subjectId: 'events-1' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: 'distinct_id', lookbackHours: 24 })
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataQualityChecksCreate).toHaveBeenCalledWith(
            '1',
            expect.objectContaining({ config: { lookback_hours: 24 } })
        )
    })

    it('offers a target window only when the referenced subject has a time column', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, { subjectType: 'view', subjectId: 'view-7' }, COLUMNS)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ checkType: 'relationships' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setCheckFormValues({ toSubjectUuid: 'table-9' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.relationshipTargetTimeColumn).toBeNull()

        logic.actions.setCheckFormValues({ toSubjectUuid: 'events-1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.relationshipTargetTimeColumn).toEqual('timestamp')
    })

    it('asks again after a failed subject catalog load', async () => {
        ;(dataQualityChecksSubjectsList as jest.Mock).mockRejectedValueOnce(new Error('down'))
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.checkSubjectsError).toEqual('down')

        logic.actions.setCheckFormValues({ checkType: 'not_null' })
        await expectLogic(logic).toFinishAllListeners()

        expect((dataQualityChecksSubjectsList as jest.Mock).mock.calls.length).toEqual(2)
        expect(logic.values.checkSubjectsError).toBeNull()
    })

    it.each<[string, DataQualitySubjectRef, CheckTypeEnumApi, string[], string | null]>([
        [
            'a PostHog table not_null check',
            { subjectType: 'posthog_table', subjectId: 'events-1' },
            CheckTypeEnumApi.NotNull,
            ['distinct_id', 'timestamp'],
            'timestamp',
        ],
        [
            'a PostHog table row_count check',
            { subjectType: 'posthog_table', subjectId: 'events-1' },
            CheckTypeEnumApi.RowCount,
            ['distinct_id', 'timestamp'],
            'timestamp',
        ],
        ['a view check', { subjectType: 'view', subjectId: 'view-7' }, CheckTypeEnumApi.NotNull, ['order_id'], null],
    ])(
        'resolves the columns and time column of %s opened for edit',
        async (_case, subject, checkType, expectedColumns, expectedTimeColumn) => {
            await mountLogic({ surface: 'overview' })

            logic.actions.openEditor(buildCheck({ check_type: checkType, config: { lookback_hours: 24 } }), subject)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.availableColumns).toEqual(expectedColumns)
            expect(logic.values.subjectTimeColumn).toEqual(expectedTimeColumn)
        }
    )

    it.each<[string, Record<string, unknown>, string[], number]>([
        ['a plain edit with known columns', { checkType: 'not_null', columnName: 'customer_id' }, COLUMNS, 0],
        ['a relationships check', { checkType: 'relationships' }, COLUMNS, 1],
        ['a subject whose columns the surface does not know', { checkType: 'not_null' }, [], 1],
    ])('loads the subject catalog only for %s', async (_case, values, columns, expected) => {
        await mountLogic()
        await openWith(null, values, columns)

        expect((dataQualityChecksSubjectsList as jest.Mock).mock.calls.length).toEqual(expected)
    })

    it('loads the subject catalog once across type switches', async () => {
        await mountLogic()
        await openWith(null, { checkType: 'relationships' })

        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: 'customer_id' })
        logic.actions.setCheckFormValues({ checkType: 'relationships' })
        await expectLogic(logic).toFinishAllListeners()

        expect((dataQualityChecksSubjectsList as jest.Mock).mock.calls.length).toEqual(1)
    })

    it('reloads the subject catalog when reopening an unscoped draft', async () => {
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.closeEditor()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openEditor(null, null)
        await expectLogic(logic).toFinishAllListeners()

        expect((dataQualityChecksSubjectsList as jest.Mock).mock.calls.length).toEqual(2)
    })
})

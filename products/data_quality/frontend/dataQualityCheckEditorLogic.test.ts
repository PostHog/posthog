import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { DataQualitySubjectRef } from './checksApi'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import {
    warehouseSavedQueriesChecksCheckTypesList,
    warehouseSavedQueriesChecksCreate,
    warehouseSavedQueriesChecksPartialUpdate,
    warehouseTablesChecksCreate,
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

// A real logic rather than a stub: the editor connects the catalog's values, and `loadCount` is how
// these tests see whether it asked for them.
jest.mock('scenes/data-management/database/databaseTableListLogic', () => {
    const { actions, kea, path, reducers } = jest.requireActual('kea')
    return {
        databaseTableListLogic: kea([
            path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
            actions({ loadDatabase: true }),
            reducers({
                views: [[]],
                dataWarehouseTables: [
                    [{ id: 'table-9', name: 'stripe_charges', fields: { customer_id: {}, amount: {} } }],
                ],
                databaseLoading: [false],
                loadCount: [0, { loadDatabase: (state: number) => state + 1 }],
            }),
        ]),
    }
})

jest.mock('./generated/api', () => ({
    warehouseSavedQueriesChecksCreate: jest.fn(),
    warehouseSavedQueriesChecksPartialUpdate: jest.fn(),
    warehouseSavedQueriesChecksCheckTypesList: jest.fn(),
    warehouseTablesChecksCreate: jest.fn(),
    warehouseTablesChecksPartialUpdate: jest.fn(),
    warehouseTablesChecksCheckTypesList: jest.fn(),
}))

const VIEW_SUBJECT: DataQualitySubjectRef = { subjectType: 'view', subjectId: 'view-1' }
const COLUMNS = ['customer_id', 'status', 'created_at', 'total']

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
        ;(warehouseSavedQueriesChecksCheckTypesList as jest.Mock).mockResolvedValue(CHECK_TYPE_CATALOG)
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic?.unmount()
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
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openWith(null, formValues)

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksCreate).toHaveBeenCalledWith('1', 'view-1', {
            check_type: checkType,
            severity: 'error',
            tags: [],
            ...expectedBody,
        })
    })

    it('sends the whole definition when an assertion is edited', async () => {
        // The old check kept its assertion; an edit now has to carry type, column and config together
        // so switching type cannot leave the previous type's config behind.
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(buildCheck({ name: 'orders_not_null', description: 'why' }), {
            checkType: 'accepted_values',
            columnName: 'status',
            acceptedValues: ['paid'],
        })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksPartialUpdate).toHaveBeenCalledWith('1', 'view-1', 'check-1', {
            check_type: 'accepted_values',
            column_name: 'status',
            config: { values: ['paid'] },
            severity: 'error',
            name: 'orders_not_null',
            description: 'why',
            tags: [],
        })
    })

    it('does not submit before the check-type catalog arrives', async () => {
        // Enter can submit while the catalog request is still pending. Without it there is no column
        // requirement to validate against, so the payload would omit column_name and be rejected.
        ;(warehouseSavedQueriesChecksCheckTypesList as jest.Mock).mockReturnValueOnce(new Promise(() => {}))
        await mountLogic()
        logic.actions.openEditor(null, VIEW_SUBJECT, COLUMNS)

        // Not toFinishAllListeners: the catalog request never settles, which is the point.
        logic.actions.submitCheckForm()
        for (let tick = 0; tick < 20; tick++) {
            await Promise.resolve()
        }

        expect(warehouseSavedQueriesChecksCreate).not.toHaveBeenCalled()
    })

    it('sends blank metadata on an edit so it can be cleared', async () => {
        // Create omits blank optional fields, which would leave an edit unable to remove a name.
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic()
        await openWith(buildCheck({ name: 'orders_not_null', description: 'why', tags: ['core'] }), {
            name: '',
            description: '',
            tags: [],
        })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksPartialUpdate).toHaveBeenCalledWith(
            '1',
            'view-1',
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

        expect(warehouseSavedQueriesChecksCreate).not.toHaveBeenCalled()
        expect(logic.values.isOpen).toBe(true)
    })

    it('creates the check once when the form is submitted twice', async () => {
        // Enter submits the form even while the save button is disabled by its loading state.
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(buildCheck({ id: 'check-new' }))
        await mountLogic()
        await openWith(null, { checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseSavedQueriesChecksCreate).toHaveBeenCalledTimes(1)
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
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockRejectedValue(apiError(data))
        await mountLogic()
        await openWith(null, { checkType: 'custom_sql', customSql: 'SELECT 1' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkFormErrors[field as 'name']).toEqual(message)
        expect(logic.values.serverError).toBeNull()
        expect(logic.values.isOpen).toBe(true)
    })

    it('shows a failure with no field of its own in the modal banner', async () => {
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockRejectedValue(
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
        ;(warehouseSavedQueriesChecksCreate as jest.Mock).mockResolvedValue(saved)
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

    it('routes an edit to the subject the check belongs to, not the surface', async () => {
        // The overview edits checks on every table and view, so the subject travels with the check.
        ;(warehouseTablesChecksCreate as jest.Mock).mockResolvedValue(buildCheck())
        await mountLogic({ surface: 'overview' })
        logic.actions.openEditor(null, { subjectType: 'table', subjectId: 'table-9' }, COLUMNS)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: 'customer_id' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(warehouseTablesChecksCreate).toHaveBeenCalledWith('1', 'table-9', expect.anything())
        expect(warehouseSavedQueriesChecksCreate).not.toHaveBeenCalled()
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
        ;(warehouseSavedQueriesChecksPartialUpdate as jest.Mock).mockResolvedValue(
            buildCheck({ description: 'written' })
        )
        await mountLogic()
        await openWith(buildCheck(), { description: 'written' })

        logic.actions.submitCheckForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(LemonDialog.open).not.toHaveBeenCalled()
        expect(logic.values.checkFormChanged).toBe(false)
    })

    it.each<[string, Record<string, unknown>, string[], number]>([
        ['a plain edit with known columns', { checkType: 'not_null', columnName: 'customer_id' }, COLUMNS, 0],
        ['a relationships check', { checkType: 'relationships' }, COLUMNS, 1],
        ['a subject whose columns the surface does not know', { checkType: 'not_null' }, [], 1],
    ])('loads the warehouse catalog only for %s', async (_case, values, columns, expected) => {
        await mountLogic()
        await openWith(null, values, columns)

        expect((databaseTableListLogic.values as unknown as { loadCount: number }).loadCount).toEqual(expected)
    })

    it('loads the warehouse catalog once across type switches', async () => {
        await mountLogic()
        await openWith(null, { checkType: 'relationships' })

        logic.actions.setCheckFormValues({ checkType: 'not_null', columnName: 'customer_id' })
        logic.actions.setCheckFormValues({ checkType: 'relationships' })
        await expectLogic(logic).toFinishAllListeners()

        expect((databaseTableListLogic.values as unknown as { loadCount: number }).loadCount).toEqual(1)
    })
})

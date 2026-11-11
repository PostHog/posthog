import { router } from 'kea-router'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogNewMetricSceneLogic, NewMetricFormValues } from './dataCatalogNewMetricSceneLogic'
import { dataCatalogMetricsApproveCreate, dataCatalogMetricsCreate, dataCatalogMetricsList } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { openOverwriteMetricDialog } from './openOverwriteMetricDialog'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        code: string | null
        data?: Record<string, any>
        constructor(
            message?: string,
            status?: number,
            _headers?: unknown,
            data?: { detail?: string; code?: string } & Record<string, any>
        ) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
            this.code = data?.code ?? null
            this.data = data
        }
    }
    return {
        __esModule: true,
        default: { insights: { list: jest.fn().mockResolvedValue({ results: [] }) } },
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

jest.mock('./openOverwriteMetricDialog', () => ({ openOverwriteMetricDialog: jest.fn() }))

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
    dataCatalogMetricsCreate: jest.fn(),
    dataCatalogMetricsApproveCreate: jest.fn(),
}))

const SQL_FORM: Partial<NewMetricFormValues> = {
    display_name: 'Monthly active users',
    name: 'monthly_active_users',
    description: 'Distinct people active in the last 30 days',
    definitionType: 'sql',
    sql: 'SELECT count(DISTINCT person_id) FROM events',
}

const CREATED_AT = '2026-10-23T12:00:00.000000Z'

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'monthly_active_users',
        description: 'Distinct people active in the last 30 days',
        definition_kind: 'HogQLQuery',
        status: 'proposed',
        is_drifted: false,
        owner: null,
        ...overrides,
    } as DataCatalogMetricApi
}

function takenNameError(): ApiError {
    return new ApiError('taken', 409, undefined, {
        code: 'metric_name_taken',
        extra: { existing_metric: { name: 'monthly_active_users', status: 'approved' } },
    })
}

describe('dataCatalogNewMetricSceneLogic', () => {
    let logic: ReturnType<typeof dataCatalogNewMetricSceneLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsList as jest.Mock).mockResolvedValue({ results: [] })
        ;(dataCatalogMetricsCreate as jest.Mock).mockResolvedValue(buildMetric({ updated_at: CREATED_AT }))
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockResolvedValue(buildMetric({ status: 'approved' }))
        initKeaTests()
        logic = dataCatalogNewMetricSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    function showInvalidQuery(form: Partial<NewMetricFormValues> = {}): void {
        logic.actions.setMetricFormValues({ ...SQL_FORM, ...form })
        logic.actions.setSqlEditorError('Error on line 10, column 5')
        logic.actions.setSqlMetadata({
            query: SQL_FORM.sql,
            errors: [{ message: 'Unable to resolve field: foo' }],
            warnings: [],
            notices: [],
        })
    }

    it.each([
        ['Create and approve', true, 1, 'Metric created and approved'],
        ['Save as proposed', false, 0, 'Metric saved as proposed'],
    ])('%s sends the definition in the create request', async (_button, approve, approveCalls, toast) => {
        logic.actions.setMetricFormValues(SQL_FORM)

        logic.actions.submitMetric(approve)
        logic.actions.submitMetric(approve)
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsCreate).toHaveBeenCalledTimes(1)
        expect((dataCatalogMetricsCreate as jest.Mock).mock.calls[0][1]).toMatchObject({
            name: 'monthly_active_users',
            display_name: 'Monthly active users',
            created_source: 'user',
            definition: { kind: 'HogQLQuery', query: 'SELECT count(DISTINCT person_id) FROM events' },
        })
        expect((dataCatalogMetricsApproveCreate as jest.Mock).mock.calls).toEqual(
            Array(approveCalls).fill(['1', 'monthly_active_users', { expected_updated_at: CREATED_AT }])
        )
        expect((lemonToast.success as jest.Mock).mock.calls.at(-1)?.[0]).toEqual(toast)
        expect(router.values.location.pathname).toContain(urls.dataCatalogMetric('monthly_active_users'))
    })

    it('does not create anything when the active definition is empty', async () => {
        logic.actions.setMetricFormValues({ ...SQL_FORM, sql: '', markdown: 'Count the users' })

        logic.actions.submitMetric(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsCreate).not.toHaveBeenCalled()
        expect(logic.values.metricFormValidationErrors.sql).toBeTruthy()
    })

    it.each([
        ['sql', true],
        ['insight', false],
        ['markdown', false],
    ] as const)('known query error with a %s definition disables saving: %s', (definitionType, disabled) => {
        showInvalidQuery({ definitionType })

        expect(!!logic.values.saveDisabledReason).toBe(disabled)
    })

    it.each([
        ['the edited query is still validating', true, 'Error on line 10, column 5: Unable to resolve field: foo'],
        ['validation of the edited query failed', false, null],
    ])('after an edit when %s', (_case, loading, message) => {
        showInvalidQuery()

        logic.actions.setMetricFormValues({ sql: 'SELECT 1' })
        logic.actions.setSqlMetadataLoading(loading)

        expect(logic.values.sqlValidationMessage).toEqual(message)
        expect(!!logic.values.saveDisabledReason).toBe(!!message)
    })

    it('never approves a confirmed overwrite', async () => {
        ;(dataCatalogMetricsCreate as jest.Mock).mockRejectedValueOnce(takenNameError())
        logic.actions.setMetricFormValues(SQL_FORM)

        logic.actions.submitMetric(true)
        await expectLogic(logic).toFinishAllListeners()
        const { onOverwrite } = (openOverwriteMetricDialog as jest.Mock).mock.calls[0][0]
        onOverwrite()
        await expectLogic(logic).toFinishAllListeners()

        expect((dataCatalogMetricsCreate as jest.Mock).mock.calls[1][1].overwrite).toBe(true)
        expect(dataCatalogMetricsApproveCreate).not.toHaveBeenCalled()
        expect((lemonToast.success as jest.Mock).mock.calls.at(-1)?.[0]).toEqual(
            'Metric overwritten. It needs approval.'
        )
    })

    it('still opens the created metric when approving it fails', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockRejectedValueOnce(new ApiError('nope', 500))
        logic.actions.setMetricFormValues(SQL_FORM)

        logic.actions.submitMetric(true)
        await expectLogic(logic).toFinishAllListeners()

        expect((lemonToast.warning as jest.Mock).mock.calls.at(-1)?.[0]).toEqual(
            'Metric created, but approving it failed. Approve it from the banner.'
        )
        expect(router.values.location.pathname).toContain(urls.dataCatalogMetric('monthly_active_users'))
    })

    it('shows the validation message until the query is valid', () => {
        showInvalidQuery()

        expect(logic.values.sqlValidationMessage).toEqual('Error on line 10, column 5: Unable to resolve field: foo')

        logic.actions.setSqlEditorError(null)
        logic.actions.setSqlMetadata({ query: SQL_FORM.sql, errors: [], warnings: [], notices: [] })

        expect(logic.values.sqlValidationMessage).toBeNull()
    })

    it('does not treat a validator failure as a known query error', () => {
        logic.actions.setMetricFormValues(SQL_FORM)
        logic.actions.setSqlEditorError('Error on line 1, column 1')
        logic.actions.setSqlMetadata({
            query: SQL_FORM.sql,
            internalError: true,
            errors: [{ message: 'Unexpected OperationalError' }],
            warnings: [],
            notices: [],
        })

        expect(logic.values.sqlValidationMessage).toBeNull()
        expect(logic.values.saveDisabledReason).toBeNull()
    })

    it('runs one test query at a time', () => {
        ;(performQuery as jest.Mock).mockReturnValue(new Promise(() => {}))
        logic.actions.setMetricFormValues(SQL_FORM)

        logic.actions.testSqlQuery()
        logic.actions.testSqlQuery()

        expect(performQuery).toHaveBeenCalledTimes(1)
    })

    it.each([
        [false, ['Data catalog', 'New metric']],
        [true, ['Data catalog', 'Metrics', 'New metric']],
    ])('with the catalog restructure %s the breadcrumbs read %j', (restructure, names) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: restructure,
            [FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE]: restructure,
        })

        expect(logic.values.breadcrumbs.map((crumb) => crumb.name)).toEqual(names)
    })
})

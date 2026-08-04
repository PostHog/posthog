import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataCatalogMetricsApproveCreate,
    dataCatalogMetricsCreate,
    dataCatalogMetricsDestroy,
    dataCatalogMetricsList,
} from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { metricsLogic } from './metricsLogic'

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
        default: { insights: { list: jest.fn().mockResolvedValue({ results: [] }) } },
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
    dataCatalogMetricsCreate: jest.fn(),
    dataCatalogMetricsApproveCreate: jest.fn(),
    dataCatalogMetricsRefreshFromInsightCreate: jest.fn(),
    dataCatalogMetricsDestroy: jest.fn(),
}))

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_active_users',
        description: 'Weekly active users',
        definition_kind: 'HogQLQuery',
        status: 'proposed',
        is_drifted: false,
        owner: null,
        ...overrides,
    } as DataCatalogMetricApi
}

describe('metricsLogic', () => {
    let logic: ReturnType<typeof metricsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsList as jest.Mock).mockResolvedValue({ results: [buildMetric()] })
        initKeaTests()
        logic = metricsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
    })

    it('replaces the row with the response when approve succeeds', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockResolvedValue(buildMetric({ status: 'approved' }))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('approved')
    })

    it('leaves the row untouched and surfaces refresh when approve returns 409', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockRejectedValue(new ApiError('drifted', 409))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('proposed')
        const errorCall = (lemonToast.error as jest.Mock).mock.calls.at(-1)
        expect(errorCall?.[1]?.button?.label).toEqual('Refresh from insight')
    })

    it('guards double-submit and closes the modal when create succeeds', async () => {
        let resolveCreate: (metric: DataCatalogMetricApi) => void = () => {}
        ;(dataCatalogMetricsCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveCreate = resolve
            })
        )

        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm({
            name: 'monthly_active_users',
            description: 'Monthly active users',
            definitionType: 'insight',
            sourceInsightShortId: 'abc123',
        })

        logic.actions.createMetric()
        logic.actions.createMetric()
        expect(dataCatalogMetricsCreate).toHaveBeenCalledTimes(1)

        resolveCreate(buildMetric({ id: 'metric-2', name: 'monthly_active_users' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newMetricModalOpen).toEqual(false)
        expect(logic.values.allMetrics.map((metric) => metric.name)).toContain('monthly_active_users')
    })

    it('does not create a SQL metric from the modal', async () => {
        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm({
            name: 'sql_metric',
            description: 'Defined in the SQL editor',
            definitionType: 'sql',
        })

        logic.actions.createMetric()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsCreate).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Create SQL metrics from the SQL editor.')
        expect(logic.values.newMetricModalOpen).toEqual(true)
    })

    it('removes the row when delete succeeds', async () => {
        ;(dataCatalogMetricsDestroy as jest.Mock).mockResolvedValue(undefined)

        logic.actions.deleteMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics).toHaveLength(0)
    })

    it('creates a metric from an insight with the short id and no definition', async () => {
        ;(dataCatalogMetricsCreate as jest.Mock).mockResolvedValue(
            buildMetric({ id: 'metric-3', name: 'from_insight', source_insight_short_id: 'abc123' })
        )

        logic.actions.openMetricFromInsightModal()
        logic.actions.createMetricFromInsight({
            name: 'from_insight',
            display_name: '',
            description: 'Snapshotted from an insight',
            source_insight_short_id: 'abc123',
        })
        await expectLogic(logic).toFinishAllListeners()

        const body = (dataCatalogMetricsCreate as jest.Mock).mock.calls.at(-1)?.[1]
        expect(body.source_insight_short_id).toEqual('abc123')
        expect(body.definition).toBeUndefined()
        expect(logic.values.metricFromInsightModalOpen).toEqual(false)
        expect(logic.values.allMetrics.map((metric) => metric.name)).toContain('from_insight')
    })
})

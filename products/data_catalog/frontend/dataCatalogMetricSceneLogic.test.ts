import { router } from 'kea-router'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogMetricSceneLogic, MARKDOWN_DEFINITION_TEMPLATE } from './dataCatalogMetricSceneLogic'
import {
    dataCatalogMetricsApproveCreate,
    dataCatalogMetricsPartialUpdate,
    dataCatalogMetricsRetrieve,
    dataCatalogMetricsRunCreate,
} from './generated/api'
import type { DataCatalogMetricApi, DataCatalogMetricRunApi } from './generated/api.schemas'

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

jest.mock('./generated/api', () => ({
    dataCatalogMetricsRetrieve: jest.fn(),
    dataCatalogMetricsApproveCreate: jest.fn(),
    dataCatalogMetricsRefreshFromInsightCreate: jest.fn(),
    dataCatalogMetricsPartialUpdate: jest.fn(),
    dataCatalogMetricsDestroy: jest.fn(),
    dataCatalogMetricsRunCreate: jest.fn(),
}))

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_active_users',
        description: 'Weekly active users',
        definition_kind: 'HogQLQuery',
        definition: { kind: 'HogQLQuery', query: 'SELECT 1' },
        status: 'approved',
        is_drifted: false,
        owner: null,
        ...overrides,
    } as DataCatalogMetricApi
}

describe('dataCatalogMetricSceneLogic', () => {
    let logic: ReturnType<typeof dataCatalogMetricSceneLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(buildMetric())
        initKeaTests()
        logic = dataCatalogMetricSceneLogic({ name: 'weekly_active_users' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMetricSuccess'])
    })

    it('saving an approved metric edit reflects the proposed status from the response', async () => {
        ;(dataCatalogMetricsPartialUpdate as jest.Mock).mockResolvedValue(
            buildMetric({ status: 'proposed', definition: { kind: 'HogQLQuery', query: 'SELECT 2' } })
        )

        logic.actions.updateMetric({ definition: { kind: 'HogQLQuery', query: 'SELECT 2' } })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.metric?.status).toEqual('proposed')
    })

    it('surfaces refresh when approve returns 409 and leaves the metric untouched', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockRejectedValue(new ApiError('drifted', 409))

        logic.actions.approveMetric()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.metric?.status).toEqual('approved')
        const errorCall = (lemonToast.error as jest.Mock).mock.calls.at(-1)
        expect(errorCall?.[1]?.button?.label).toEqual('Refresh from insight')
    })

    it('stores the run result envelope', async () => {
        const envelope: Partial<DataCatalogMetricRunApi> = {
            status: 'approved',
            results: [{ value: 5 }],
            instructions: null,
            compiled_query: 'SELECT count()',
            posthog_url: 'https://us.posthog.com/project/1/sql',
        }
        ;(dataCatalogMetricsRunCreate as jest.Mock).mockResolvedValue(envelope)

        logic.actions.loadRunResult()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runResult?.compiled_query).toEqual('SELECT count()')
    })

    it('discards the edited draft when the definition editor closes without saving', async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({
                name: 'markdown_metric',
                definition_kind: 'MarkdownDefinition',
                definition: { kind: 'MarkdownDefinition', markdown: '1. Count the users' },
            })
        )
        const markdownLogic = dataCatalogMetricSceneLogic({ name: 'markdown_metric' })
        markdownLogic.mount()
        await expectLogic(markdownLogic).toDispatchActions(['loadMetricSuccess'])

        markdownLogic.actions.setEditingDefinition(true)
        markdownLogic.actions.setDraftMarkdown('edited but abandoned')
        markdownLogic.actions.setEditingDefinition(false)
        await expectLogic(markdownLogic).toFinishAllListeners()

        expect(markdownLogic.values.draftMarkdown).toEqual('1. Count the users')
        markdownLogic.unmount()
    })

    it('keeps the in-progress draft when the metric reloads while the editor is open', async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({
                name: 'markdown_metric',
                definition_kind: 'MarkdownDefinition',
                definition: { kind: 'MarkdownDefinition', markdown: '1. Count the users' },
            })
        )
        const markdownLogic = dataCatalogMetricSceneLogic({ name: 'markdown_metric' })
        markdownLogic.mount()
        await expectLogic(markdownLogic).toDispatchActions(['loadMetricSuccess'])

        markdownLogic.actions.setEditingDefinition(true)
        markdownLogic.actions.setDraftMarkdown('1. Count the users who paid')
        // A second load lands while the editor is open, e.g. revisiting the route.
        markdownLogic.actions.loadMetric()
        await expectLogic(markdownLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(markdownLogic.values.draftMarkdown).toEqual('1. Count the users who paid')
        markdownLogic.unmount()
    })

    it('starting markdown editing on a stub seeds the template without saving', async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({ name: 'stub_metric', definition_kind: null, definition: null, status: 'proposed' })
        )
        const stubLogic = dataCatalogMetricSceneLogic({ name: 'stub_metric' })
        stubLogic.mount()
        await expectLogic(stubLogic).toDispatchActions(['loadMetricSuccess'])

        stubLogic.actions.startEditingMarkdown()
        await expectLogic(stubLogic).toFinishAllListeners()

        expect(stubLogic.values.editingDefinition).toBe(true)
        expect(stubLogic.values.draftMarkdown).toEqual(MARKDOWN_DEFINITION_TEMPLATE)
        expect(dataCatalogMetricsPartialUpdate).not.toHaveBeenCalled()
        stubLogic.unmount()
    })

    it('renaming issues the patch against the old name and navigates to the new URL', async () => {
        ;(dataCatalogMetricsPartialUpdate as jest.Mock).mockResolvedValue(buildMetric({ name: 'wau' }))

        logic.actions.renameMetric('wau')
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsPartialUpdate).toHaveBeenCalledWith('1', 'weekly_active_users', { name: 'wau' })
        expect(router.values.location.pathname).toContain('/wau')
    })

    it('renaming to an invalid name issues no request', async () => {
        logic.actions.renameMetric('has-dash')
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsPartialUpdate).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('opens the markdown editor once loaded when arriving with ?edit=definition', async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({ name: 'stub_metric', definition_kind: null, definition: null, status: 'proposed' })
        )
        const stubLogic = dataCatalogMetricSceneLogic({ name: 'stub_metric' })
        stubLogic.mount()
        await expectLogic(stubLogic).toDispatchActions(['loadMetricSuccess'])

        router.actions.push(urls.dataCatalogMetric('stub_metric'), { edit: 'definition' })
        await expectLogic(stubLogic).toDispatchActions(['loadMetricSuccess'])

        expect(stubLogic.values.editingDefinition).toBe(true)
        expect(stubLogic.values.draftMarkdown).toEqual(MARKDOWN_DEFINITION_TEMPLATE)
        expect(router.values.searchParams.edit).toBeUndefined()
        stubLogic.unmount()
    })

    it('issues no requests for a traversal-shaped metric name', async () => {
        // props.name is interpolated unencoded into the request path, so a "../"-shaped route
        // value must never reach retrieve/run/approve/refresh/update/delete.
        jest.clearAllMocks()
        const traversalLogic = dataCatalogMetricSceneLogic({ name: '../../../1/data_catalog/metrics/other' })
        traversalLogic.mount()
        await expectLogic(traversalLogic).toDispatchActions(['loadMetricFailure'])

        traversalLogic.actions.approveMetric()
        traversalLogic.actions.refreshMetricFromInsight()
        traversalLogic.actions.updateMetric({ definition: { kind: 'HogQLQuery', query: 'SELECT 2' } })
        traversalLogic.actions.renameMetric('valid_name')
        traversalLogic.actions.deleteMetric()
        traversalLogic.actions.loadRunResult()
        await expectLogic(traversalLogic).toFinishAllListeners()

        expect(dataCatalogMetricsRetrieve).not.toHaveBeenCalled()
        expect(dataCatalogMetricsRunCreate).not.toHaveBeenCalled()
        expect(dataCatalogMetricsApproveCreate).not.toHaveBeenCalled()
        expect(dataCatalogMetricsPartialUpdate).not.toHaveBeenCalled()

        traversalLogic.unmount()
    })
})

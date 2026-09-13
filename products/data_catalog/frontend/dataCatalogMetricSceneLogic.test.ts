import { router } from 'kea-router'

import { ApiConfig, ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogAgentSyncLogic } from './dataCatalogAgentSyncLogic'
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

    afterEach(() => {
        ;(ApiConfig.getCurrentTeamId as jest.Mock).mockReturnValue(1)
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

    it('carries an open markdown draft to an externally renamed metric once', async () => {
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({
                name: 'daily_paying_users',
                definition_kind: 'MarkdownDefinition',
                definition: { kind: 'MarkdownDefinition', markdown: '1. Count the users' },
            })
        )
        logic.actions.setEditingDefinition(true)
        logic.actions.setDraftMarkdown('1. Count users who paid')
        logic.actions.renamedExternally('daily_paying_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain('/daily_paying_users')

        const renamedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        renamedLogic.mount()
        await expectLogic(renamedLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(renamedLogic.values.editingDefinition).toBe(true)
        expect(renamedLogic.values.draftMarkdown).toEqual('1. Count users who paid')
        renamedLogic.unmount()

        const reloadedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        reloadedLogic.mount()
        await expectLogic(reloadedLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(reloadedLogic.values.editingDefinition).toBe(false)
        expect(reloadedLogic.values.draftMarkdown).toEqual('1. Count the users')
        reloadedLogic.unmount()
    })

    it('drops a carried draft when the rename also switched the definition to a query kind', async () => {
        // One agent call can rename the metric and replace its definition. The query-kind view has
        // no markdown editor, so restoring the draft would leave text the user cannot reach.
        logic.actions.setEditingDefinition(true)
        logic.actions.setDraftMarkdown('1. Count users who paid')
        logic.actions.renamedExternally('daily_paying_users')
        await expectLogic(logic).toFinishAllListeners()

        const renamedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        renamedLogic.mount()
        await expectLogic(renamedLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(renamedLogic.values.editingDefinition).toBe(false)
        expect(renamedLogic.values.draftMarkdown).toEqual('')
        renamedLogic.unmount()
    })

    it('closes the open editor when the definition becomes a query kind', async () => {
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
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({ name: 'markdown_metric', definition_kind: 'HogQLQuery' })
        )
        markdownLogic.actions.loadMetric()
        await expectLogic(markdownLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(markdownLogic.values.editingDefinition).toBe(false)
        expect(markdownLogic.values.draftSql).toEqual('SELECT 1')
        markdownLogic.unmount()
    })

    it('does not reopen a carried draft after the load it was handed to fails', async () => {
        logic.actions.setEditingDefinition(true)
        logic.actions.setDraftMarkdown('1. Count users who paid')
        logic.actions.renamedExternally('daily_paying_users')
        await expectLogic(logic).toFinishAllListeners()
        ;(dataCatalogMetricsRetrieve as jest.Mock).mockRejectedValueOnce(new ApiError('gone', 404))

        const failedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        failedLogic.mount()
        await expectLogic(failedLogic).toDispatchActions(['loadMetricFailure']).toFinishAllListeners()
        failedLogic.unmount()

        ;(dataCatalogMetricsRetrieve as jest.Mock).mockResolvedValue(
            buildMetric({
                name: 'daily_paying_users',
                definition_kind: 'MarkdownDefinition',
                definition: { kind: 'MarkdownDefinition', markdown: '1. Count the users' },
            })
        )
        const revisitedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        revisitedLogic.mount()
        await expectLogic(revisitedLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(revisitedLogic.values.editingDefinition).toBe(false)
        expect(revisitedLogic.values.draftMarkdown).toEqual('1. Count the users')
        revisitedLogic.unmount()
    })

    it('does not carry a draft when an externally renamed metric is not being edited', async () => {
        logic.actions.renamedExternally('daily_paying_users')
        await expectLogic(logic).toFinishAllListeners()

        const renamedLogic = dataCatalogMetricSceneLogic({ name: 'daily_paying_users' })
        renamedLogic.mount()
        await expectLogic(renamedLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(renamedLogic.values.editingDefinition).toBe(false)
        expect(renamedLogic.values.draftMarkdown).toEqual('')
        renamedLogic.unmount()
    })

    it('does not restore a handed-off draft into a same-named metric in another project', async () => {
        logic.actions.setEditingDefinition(true)
        logic.actions.setDraftMarkdown('1. Count users who paid')
        logic.actions.renamedExternally('cross_project_metric')
        await expectLogic(logic).toFinishAllListeners()

        // The rename target's load in project 1 never consumed the draft (it failed or was
        // interrupted). Opening the same metric name in another project must not restore it.
        ;(ApiConfig.getCurrentTeamId as jest.Mock).mockReturnValue(2)
        const otherProjectLogic = dataCatalogMetricSceneLogic({ name: 'cross_project_metric' })
        otherProjectLogic.mount()
        await expectLogic(otherProjectLogic).toDispatchActions(['loadMetricSuccess']).toFinishAllListeners()

        expect(otherProjectLogic.values.editingDefinition).toBe(false)
        expect(otherProjectLogic.values.draftMarkdown).toEqual('')
        otherProjectLogic.unmount()
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

    it('keeps the shared open-metric slot when the previous instance unmounts after the rename target mounts', async () => {
        // A rename mounts the new keyed instance before React releases the old one. The old
        // instance's late unmount must not blank the metric the new instance registered.
        const renamedLogic = dataCatalogMetricSceneLogic({ name: 'wau' })
        renamedLogic.mount()
        await expectLogic(renamedLogic).toDispatchActions(['loadMetricSuccess'])

        logic.unmount()

        expect(dataCatalogAgentSyncLogic.values.openMetricName).toEqual('wau')
        renamedLogic.unmount()
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

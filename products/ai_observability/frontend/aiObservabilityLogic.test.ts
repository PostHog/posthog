import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { emptySceneParams } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { productRedirects } from '~/products'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { sceneLogic } from '../../../frontend/src/scenes/sceneLogic'
import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'
import { DisplayOption, aiObservabilityTraceLogic } from './aiObservabilityTraceLogic'
import { llmSessionTitleLazyLoaderLogic } from './llmSessionTitleLazyLoaderLogic'
import { aiObservabilityDashboardLogic } from './tabs/aiObservabilityDashboardLogic'
import { aiObservabilityGenerationsLogic } from './tabs/aiObservabilityGenerationsLogic'
import { aiObservabilitySessionsViewLogic } from './tabs/aiObservabilitySessionsViewLogic'
import { aiObservabilityTracesTabLogic } from './tabs/aiObservabilityTracesTabLogic'

type RedirectParams = Record<string, string>

const redirectUrl = (
    path: string,
    params: RedirectParams = {},
    searchParams: RedirectParams = {},
    hashParams: RedirectParams = {}
): string => {
    const redirect = productRedirects[path]
    return typeof redirect === 'function' ? redirect(params, searchParams, hashParams) : redirect
}

describe('LLM analytics URL split', () => {
    it('uses the new canonical product URLs', () => {
        expect(urls.aiObservabilityDashboard()).toBe('/ai-observability/dashboard')
        expect(urls.aiObservabilityReviews()).toBe('/ai-observability/reviews')
        expect(urls.aiObservabilityTrace('trace-1')).toBe('/ai-observability/traces/trace-1')
        expect(urls.aiObservabilityDatasets()).toBe('/ai-evals/datasets')
        expect(urls.aiObservabilityTags()).toBe('/ai-evals/taggers')
        expect(urls.aiObservabilityEvaluations()).toBe('/ai-evals/evaluations')
        expect(urls.aiObservabilityPrompts()).toBe('/prompt-management/prompts')
    })

    it('redirects legacy LLM analytics URLs to their new product areas', () => {
        expect(redirectUrl('/llm-analytics')).toBe('/ai-observability/dashboard')
        expect(redirectUrl('/llm-analytics/settings')).toBe('/settings/project-ai-observability#ai-observability-byok')
        expect(redirectUrl('/llm-analytics/settings', {}, {}, { 'llm-analytics-byok': 'true' })).toBe(
            '/settings/project-ai-observability#ai-observability-byok'
        )
        expect(redirectUrl('/llm-analytics/reviews', {}, { queue_id: 'queue-1' })).toBe(
            '/ai-observability/reviews?queue_id=queue-1'
        )
        expect(redirectUrl('/llm-analytics/traces/:id', { id: 'trace-1' }, { event: 'event-1' })).toBe(
            '/ai-observability/traces/trace-1?event=event-1'
        )
        expect(redirectUrl('/llm-analytics/datasets/:id', { id: 'dataset-1' }, { item: 'item-1' })).toBe(
            '/ai-evals/datasets/dataset-1?item=item-1'
        )
        expect(redirectUrl('/llm-analytics/tags/:id', { id: 'tagger-1' })).toBe('/ai-evals/taggers/tagger-1')
        expect(redirectUrl('/llm-analytics/evaluations/:id', { id: 'evaluation-1' })).toBe(
            '/ai-evals/evaluations/evaluation-1'
        )
        expect(redirectUrl('/llm-analytics/prompts/:name', { name: 'prompt-1' })).toBe(
            '/prompt-management/prompts/prompt-1'
        )
    })

    it('redirects AI observability settings to the project-level BYOK setting', () => {
        expect(redirectUrl('/ai-observability/settings')).toBe(
            '/settings/project-ai-observability#ai-observability-byok'
        )
    })
})

describe('aiObservabilitySharedLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySharedLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic.mount()
        router.actions.push(urls.aiObservabilityTraces())
        logic = aiObservabilitySharedLogic({})
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('should handle URL parameters correctly', () => {
        const filters = [
            {
                type: 'event',
                key: 'browser',
                value: 'Chrome',
                operator: 'exact',
            },
        ]

        // Navigate with various parameters
        router.actions.push(urls.aiObservabilityTraces(), {
            filters: filters,
            date_from: '-14d',
            date_to: '-1d',
            filter_test_accounts: 'true',
        })

        // Should apply all parameters
        expectLogic(logic).toMatchValues({
            propertyFilters: filters,
            dateFilter: {
                dateFrom: '-14d',
                dateTo: '-1d',
            },
            shouldFilterTestAccounts: true,
        })
    })

    it('preserves params owned by other logics when rewriting the URL', () => {
        // review_* / human_reviews_tab ride along on tab links — applying shared
        // state must not strip them
        router.actions.push(urls.aiObservabilityGenerations(), {
            date_from: '-14d',
            review_search: 'needs review',
            human_reviews_tab: 'reviews',
        })

        expectLogic(logic).toMatchValues({
            dateFilter: { dateFrom: '-14d', dateTo: null },
        })
        expect(router.values.searchParams).toMatchObject({
            review_search: 'needs review',
            human_reviews_tab: 'reviews',
        })
    })

    it('strips stale trace-view params while keeping foreign params', () => {
        router.actions.push(urls.aiObservabilityTraces(), {
            event: 'event-1',
            timestamp: '2026-01-01',
            review_search: 'abc',
        })

        expect(router.values.searchParams).toEqual({ review_search: 'abc' })
    })

    it('should reset filters when switching tabs without params', () => {
        // Set some filters first
        logic.actions.setPropertyFilters([
            {
                type: PropertyFilterType.Event,
                key: 'test',
                value: 'value',
                operator: PropertyOperator.Exact,
            },
        ])
        logic.actions.setDates('-30d', '-1d')
        logic.actions.setShouldFilterTestAccounts(true)

        // Navigate to another tab without params
        router.actions.push(urls.aiObservabilityGenerations())

        // Should reset to defaults
        expectLogic(logic).toMatchValues({
            propertyFilters: [],
            dateFilter: {
                dateFrom: '-1h',
                dateTo: null,
            },
            shouldFilterTestAccounts: false,
        })
    })
})

describe('aiObservabilitySessionsViewLogic', () => {
    let sharedLogic: ReturnType<typeof aiObservabilitySharedLogic.build>
    let logic: ReturnType<typeof aiObservabilitySessionsViewLogic.build>
    let querySpy: jest.SpyInstance
    const sessionColumns = ['session_id', 'distinct_id', 'traces', 'total_cost', 'total_latency', 'errors', 'last_seen']

    const urlState = {
        propertyFilters: [],
        dateFrom: '-14d',
        dateTo: null,
        shouldFilterTestAccounts: false,
        datesChanged: true,
    }

    async function settleListeners(): Promise<void> {
        for (let i = 0; i < 5; i++) {
            await Promise.resolve()
        }
    }

    function setActiveTab(sceneKey: string): void {
        sceneLogic.actions.setScene('AIObservability', sceneKey, emptySceneParams)
    }

    function sessionRow(index: number): unknown[] {
        return [
            `session-${index}`,
            `person-${index}`,
            1,
            0,
            0.5,
            0,
            `2026-01-01T00:${String(index).padStart(2, '0')}:00Z`,
        ]
    }

    function sessionResponse(indexes: number[]): { columns: string[]; results: unknown[][] } {
        return {
            columns: sessionColumns,
            results: indexes.map((index) => sessionRow(index)),
        }
    }

    function deferredResponse(): {
        promise: Promise<{ columns: string[]; results: unknown[][] }>
        resolve: (response: { columns: string[]; results: unknown[][] }) => void
        reject: (error: unknown) => void
    } {
        let resolve!: (response: { columns: string[]; results: unknown[][] }) => void
        let reject!: (error: unknown) => void
        const promise = new Promise<{ columns: string[]; results: unknown[][] }>((promiseResolve, promiseReject) => {
            resolve = promiseResolve
            reject = promiseReject
        })
        return { promise, resolve, reject }
    }

    beforeEach(() => {
        initKeaTests()
        querySpy = jest.spyOn(api, 'query').mockResolvedValue({
            columns: sessionColumns,
            results: [],
        } as any)
        sceneLogic.mount()
        sharedLogic = aiObservabilitySharedLogic({})
        sharedLogic.mount()
        logic = aiObservabilitySessionsViewLogic({})
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        sharedLogic.unmount()
        sceneLogic.unmount()
        jest.restoreAllMocks()
    })

    it('reloads URL-applied session filters while the sessions tab is visible', async () => {
        setActiveTab('aiObservabilitySessions')
        querySpy.mockClear()
        // Non-empty so the empty-state probe doesn't fire a second query.
        querySpy.mockResolvedValue(sessionResponse([1]))

        sharedLogic.actions.applyUrlState(urlState)
        await settleListeners()

        expect(querySpy).toHaveBeenCalledTimes(1)
    })

    it('does not reload sessions for hidden-tab URL state changes', async () => {
        setActiveTab('aiObservabilityTraces')
        querySpy.mockClear()

        sharedLogic.actions.applyUrlState(urlState)
        await settleListeners()

        expect(querySpy).not.toHaveBeenCalled()
    })

    it('ignores stale session reloads after filters change', async () => {
        setActiveTab('aiObservabilitySessions')
        const staleResponse = deferredResponse()
        const freshResponse = deferredResponse()
        querySpy.mockImplementationOnce(() => staleResponse.promise).mockImplementationOnce(() => freshResponse.promise)

        logic.actions.loadSessions()
        await settleListeners()

        sharedLogic.actions.applyUrlState(urlState)
        await settleListeners()

        freshResponse.resolve(sessionResponse([2]))
        await settleListeners()
        expect(logic.values.sessions.map((session) => session.sessionId)).toEqual(['session-2'])
        expect(logic.values.sessionsLoading).toBe(false)

        staleResponse.resolve(sessionResponse([1]))
        await settleListeners()
        expect(logic.values.sessions.map((session) => session.sessionId)).toEqual(['session-2'])
        expect(querySpy).toHaveBeenCalledTimes(2)
    })

    it('drops a superseded response without surfacing an error when filters change on a hidden tab', async () => {
        setActiveTab('aiObservabilityTraces')
        const staleResponse = deferredResponse()
        querySpy.mockImplementationOnce(() => staleResponse.promise)

        logic.actions.loadSessions()
        await settleListeners()

        // No reload fires for a hidden tab, so only the stale-source bail catches this response.
        sharedLogic.actions.applyUrlState(urlState)
        await settleListeners()

        staleResponse.resolve(sessionResponse([1]))
        await settleListeners()

        expect(logic.values.sessions).toHaveLength(0)
        expect(logic.values.sessionsLoading).toBe(false)
        expect(logic.values.sessionsError).toBeNull()
    })

    it('ignores stale load-more responses after a first-page reload', async () => {
        querySpy.mockResolvedValueOnce(sessionResponse(Array.from({ length: 50 }, (_, i) => i)))

        logic.actions.loadSessions()
        await settleListeners()
        expect(logic.values.sessions).toHaveLength(50)
        expect(logic.values.hasMoreSessions).toBe(true)

        const staleLoadMoreResponse = deferredResponse()
        const refreshResponse = deferredResponse()
        querySpy
            .mockImplementationOnce(() => staleLoadMoreResponse.promise)
            .mockImplementationOnce(() => refreshResponse.promise)

        logic.actions.loadMoreSessions()
        await settleListeners()
        expect(logic.values.moreSessionsLoading).toBe(true)

        logic.actions.loadSessions({ refresh: 'force_blocking' })
        await settleListeners()
        expect(logic.values.moreSessionsLoading).toBe(false)

        refreshResponse.resolve(sessionResponse([60]))
        await settleListeners()
        expect(logic.values.sessions.map((session) => session.sessionId)).toEqual(['session-60'])

        staleLoadMoreResponse.resolve(sessionResponse([50]))
        await settleListeners()
        expect(logic.values.sessions.map((session) => session.sessionId)).toEqual(['session-60'])
        expect(querySpy).toHaveBeenCalledTimes(3)
    })

    it('appends additional session pages', async () => {
        let page = 0
        querySpy.mockImplementation(() => {
            page += 1
            return Promise.resolve({
                columns: sessionColumns,
                results: page === 1 ? Array.from({ length: 50 }, (_, i) => sessionRow(i)) : [sessionRow(50)],
            })
        })

        logic.actions.loadSessions()
        await settleListeners()
        expect(logic.values.sessions).toHaveLength(50)
        expect(logic.values.hasMoreSessions).toBe(true)

        logic.actions.loadMoreSessions()
        await settleListeners()
        expect(logic.values.sessions).toHaveLength(51)
        expect(logic.values.sessions[50].sessionId).toBe('session-50')
        expect(logic.values.hasMoreSessions).toBe(false)
        expect(querySpy).toHaveBeenCalledTimes(2)
    })

    it('preloads titles for appended session pages', async () => {
        const titleLogic = llmSessionTitleLazyLoaderLogic()
        titleLogic.mount()
        try {
            querySpy.mockResolvedValueOnce(sessionResponse(Array.from({ length: 50 }, (_, i) => i)))
            querySpy.mockResolvedValueOnce(sessionResponse([50]))

            logic.actions.loadSessions()
            await settleListeners()
            expect(logic.values.hasMoreSessions).toBe(true)

            logic.actions.loadMoreSessions()
            await settleListeners()

            expect(logic.values.sessions[50].sessionId).toBe('session-50')
            expect(titleLogic.values.loadingSessionIds.has('session-50')).toBe(true)
        } finally {
            titleLogic.unmount()
        }
    })

    it('surfaces a retryable timeout state when the sessions query hangs', async () => {
        jest.useFakeTimers()
        try {
            querySpy.mockImplementation(() => deferredResponse().promise) // never settles

            logic.actions.loadSessions()
            await settleListeners()
            expect(logic.values.sessionsLoading).toBe(true)

            jest.advanceTimersByTime(60_000)
            await settleListeners()

            expect(logic.values.sessionsLoading).toBe(false)
            expect(logic.values.sessionsError).toBe('timeout')
        } finally {
            jest.useRealTimers()
        }
    })

    it('surfaces a retryable error state when the sessions query fails', async () => {
        querySpy.mockRejectedValue(new Error('boom'))

        logic.actions.loadSessions()
        await settleListeners()

        expect(logic.values.sessionsLoading).toBe(false)
        expect(logic.values.sessionsError).toBe('error')
        expect(logic.values.sessions).toHaveLength(0)
    })

    it.each([
        ['no-session-ids', [[1]]],
        ['no-data', []],
    ])('classifies an empty list as %s when the probe returns %j', async (expectedReason, probeResults) => {
        querySpy
            .mockResolvedValueOnce({ columns: sessionColumns, results: [] })
            .mockResolvedValueOnce({ results: probeResults })

        logic.actions.loadSessions()
        await settleListeners()
        await settleListeners()

        expect(logic.values.sessions).toHaveLength(0)
        expect(logic.values.sessionsEmptyReason).toBe(expectedReason)
    })

    it('holds the loading state until the empty-reason probe settles', async () => {
        const probe = deferredResponse()
        querySpy
            .mockResolvedValueOnce({ columns: sessionColumns, results: [] })
            .mockImplementationOnce(() => probe.promise)

        logic.actions.loadSessions()
        await settleListeners()

        expect(logic.values.sessionsLoading).toBe(true)
        expect(logic.values.sessions).toHaveLength(0)

        probe.resolve({ columns: [], results: [[1]] })
        await settleListeners()

        expect(logic.values.sessionsLoading).toBe(false)
        expect(logic.values.sessionsEmptyReason).toBe('no-session-ids')
    })
})

describe('AI observability persisted preferences', () => {
    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        window.localStorage.clear()
    })

    it('persists generation column preferences across remount', () => {
        const columns = ['uuid', 'timestamp']
        const firstLogic = aiObservabilityGenerationsLogic()
        firstLogic.mount()
        firstLogic.actions.setGenerationsColumns(columns)
        firstLogic.unmount()

        const secondLogic = aiObservabilityGenerationsLogic()
        secondLogic.mount()

        expect(secondLogic.values.generationsColumns).toEqual(columns)

        secondLogic.unmount()
    })

    it('persists traces table preferences across remount', () => {
        const firstLogic = aiObservabilityTracesTabLogic()
        firstLogic.mount()
        firstLogic.actions.setShowInputOutputColumns(false)
        firstLogic.unmount()

        const secondLogic = aiObservabilityTracesTabLogic()
        secondLogic.mount()

        expect(secondLogic.values.showInputOutputColumns).toBe(false)

        secondLogic.unmount()
    })

    it('persists selected dashboard across remount', () => {
        const firstLogic = aiObservabilityDashboardLogic()
        firstLogic.mount()
        firstLogic.actions.loadLLMDashboardsSuccess([{ id: 42, name: 'AI dashboard', description: '' }])
        firstLogic.unmount()

        const secondLogic = aiObservabilityDashboardLogic()
        secondLogic.mount()

        expect(secondLogic.values.selectedDashboardId).toBe(42)

        secondLogic.unmount()
    })

    it('persists trace display preferences across remount', () => {
        const firstLogic = aiObservabilityTraceLogic()
        firstLogic.mount()
        firstLogic.actions.setIsRenderingMarkdown(false)
        firstLogic.actions.setIsRenderingXml(true)
        firstLogic.actions.setDisplayOption(DisplayOption.TextView)
        firstLogic.actions.setTraceReviewPanelExpanded(true)
        firstLogic.unmount()

        const secondLogic = aiObservabilityTraceLogic()
        secondLogic.mount()

        expect(secondLogic.values.isRenderingMarkdown).toBe(false)
        expect(secondLogic.values.isRenderingXml).toBe(true)
        expect(secondLogic.values.displayOption).toBe(DisplayOption.TextView)
        expect(secondLogic.values.isTraceReviewPanelExpanded).toBe(true)

        secondLogic.unmount()
    })

    it('scopes explicit storage keys to the current team', () => {
        const logic = aiObservabilityTraceLogic()
        logic.mount()
        logic.actions.setIsRenderingMarkdown(false)

        const storageKey = `${MOCK_TEAM_ID}__ai_observability.trace.isRenderingMarkdown`
        expect(window.localStorage[storageKey]).toBe('false')
        expect(
            Object.getOwnPropertyNames(window.localStorage).filter((key) => key.endsWith('trace.isRenderingMarkdown'))
        ).toEqual([storageKey])

        logic.unmount()
    })
})

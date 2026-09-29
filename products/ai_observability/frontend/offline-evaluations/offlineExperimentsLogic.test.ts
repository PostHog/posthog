import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineExperimentPageApi } from '../generated/api.schemas'
import { offlineExperimentsLogic } from './offlineExperimentsLogic'
import { overviewExperiments, overviewScorers, overviewHistory } from './offlineOverviewFixtures'
import { readOfflineScorerPreferences, saveOfflineScorerPreferences } from './offlineOverviewState'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsList: jest.fn(),
    aiObservabilityOfflineExperimentsScorerSummariesList: jest.fn(),
    llmAnalyticsScoreDefinitionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
}))

const page: OfflineExperimentPageApi = { results: overviewExperiments, count: 100, next_cursor: 'cursor-2' }
const props = { teamId: 997, userId: 1, timezone: 'America/Toronto' }
const list = jest.mocked(api.aiObservabilityOfflineExperimentsList)

describe('offlineExperimentsLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-09-28T14:00:00Z') })
        initKeaTests()
        jest.resetAllMocks()
        localStorage.clear()
        list.mockResolvedValue(page)
        jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList).mockResolvedValue({
            results: overviewScorers.map((scorer) => overviewHistory(scorer)[0].summary),
            count: 3,
            next_cursor: null,
        })
        jest.mocked(api.llmAnalyticsScoreDefinitionsList).mockResolvedValue({
            results: overviewScorers,
            count: 3,
            next: null,
            previous: null,
        })
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockImplementation(async (_team, id) => {
            const scorer = overviewScorers.find((item) => item.id === id)
            if (!scorer) {
                throw new Error('Not found')
            }
            return scorer
        })
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), { scores: overviewScorers[0].id })
    })

    afterEach(() => jest.useRealTimers())

    it('keeps the active chart hover when another chart leaves and clears it when filters change', () => {
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        logic.actions.setHoveredTrend('first', 1000)
        logic.actions.setHoveredTrend('second', 2000)
        logic.actions.clearHoveredTrend('first')
        expect(logic.values.hoveredTrend?.timestamp).toBe(2000)

        logic.actions.clearHoveredTrend('second')
        expect(logic.values.hoveredTrend).toBeNull()

        logic.actions.setHoveredTrend('second', 2000)
        logic.actions.setFilters({ run_source: 'ci' })
        expect(logic.values.hoveredTrend).toBeNull()
    })

    it.each(['new', 'saved empty', 'URL empty'])(
        'selects recent scorers when the selection is %s',
        async (selection) => {
            if (selection === 'saved empty') {
                saveOfflineScorerPreferences(props.userId, props.teamId, [])
            }
            router.actions.push(
                urls.aiObservabilityOfflineEvaluations(),
                selection === 'URL empty' ? { scores: '' } : {}
            )
            const logic = offlineExperimentsLogic(props)
            logic.mount()
            await jest.advanceTimersByTimeAsync(150)

            expect(logic.values.scorerIds).toEqual(overviewScorers.map(({ id }) => id))
            expect(router.values.searchParams.scores).toBe(overviewScorers.map(({ id }) => id).join(','))
        }
    )

    it('falls back to available definitions after clearing the chosen scorers', async () => {
        jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList).mockResolvedValue({
            results: [],
            count: 0,
            next_cursor: null,
        })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        logic.actions.setScorerIds([])
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.scorerIds).toEqual(overviewScorers.map(({ id }) => id))
    })

    it('reports a failed score suggestion and clears it when a retry succeeds', async () => {
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), {})
        jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList).mockRejectedValueOnce(
            new Error('Summaries failed')
        )
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.scorerIds).toEqual([])
        expect(logic.values.suggestedScorersError).toBe(true)

        logic.actions.loadOfflineSuggestedScorers()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.suggestedScorersError).toBe(false)
        expect(logic.values.scorerIds).toEqual(overviewScorers.map(({ id }) => id))
    })

    it('uses shared URL score selections without overwriting personal preferences', async () => {
        const saved = [overviewScorers[0].id]
        const shared = [overviewScorers[1].id]
        saveOfflineScorerPreferences(props.userId, props.teamId, saved)
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), { scores: shared.join(',') })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.scorerIds).toEqual(shared)
        expect(readOfflineScorerPreferences(props.userId, props.teamId)).toEqual(saved)

        logic.actions.setFilters({ search: 'a run' })
        await jest.advanceTimersByTimeAsync(150)
        expect(readOfflineScorerPreferences(props.userId, props.teamId)).toEqual(saved)

        logic.actions.openChooser()
        logic.actions.setDraftScorerIds([])
        logic.actions.saveScorers()
        expect(readOfflineScorerPreferences(props.userId, props.teamId)).toEqual([])
    })

    it.each([true, false])(
        'names a selected archived scorer outside the options page when the chooser opens (readable: %s)',
        async (readable) => {
            const archived = { ...overviewScorers[0], id: '00000000-0000-4000-8000-0000000000aa', archived: true }
            const retrieve = jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve)
            if (readable) {
                retrieve.mockImplementation(async (_team, id) => {
                    const scorer = [...overviewScorers, archived].find((item) => item.id === id)
                    if (!scorer) {
                        throw new Error('Not found')
                    }
                    return scorer
                })
            }
            router.actions.push(urls.aiObservabilityOfflineEvaluations(), {
                scores: [overviewScorers[1].id, archived.id].join(','),
            })
            const logic = offlineExperimentsLogic(props)
            logic.mount()
            await jest.advanceTimersByTimeAsync(150)
            logic.actions.openChooser()
            await jest.advanceTimersByTimeAsync(150)

            expect(retrieve).toHaveBeenCalledWith(String(props.teamId), archived.id)
            expect(logic.values.scorersById[archived.id]?.name).toBe(readable ? archived.name : undefined)
            expect(logic.values.draftScorerIds).toEqual([overviewScorers[1].id, archived.id])
        }
    )

    it('shares the date window, source, and upload state while preserving pagination on Back', async () => {
        const saved = [overviewScorers[0].id]
        saveOfflineScorerPreferences(props.userId, props.teamId, saved)
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), {
            scores: saved.join(','),
            date_from: '-24h',
            run_source: 'local',
            statuses: 'uploading',
        })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        const initialRange = logic.values.dateRange
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: initialRange?.dateFrom,
            date_to: initialRange?.dateTo,
            run_source: 'local',
            statuses: 'uploading',
        })
        expect(logic.values.trendFilters).toEqual({ run_source: 'local', statuses: 'uploading' })

        jest.setSystemTime(new Date('2026-09-28T15:00:00Z'))
        logic.actions.nextPage('cursor-2')
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.dateRange).toEqual(initialRange)
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: initialRange?.dateFrom,
            date_to: initialRange?.dateTo,
            cursor: 'cursor-2',
        })
        const listUrl = combineUrl(router.values.location.pathname, router.values.searchParams)
        const listSearch = { ...router.values.searchParams }

        logic.actions.setFilters({ search: 'a run' })
        expect(logic.values.dateRange).toEqual(initialRange)

        logic.actions.setFilters({ date_from: '-7d', run_source: 'ci', statuses: 'failed' })
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.cursorStack).toEqual([])
        expect(logic.values.trendFilters).toEqual({ run_source: 'ci', statuses: 'failed' })
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: logic.values.dateRange?.dateFrom,
            date_to: logic.values.dateRange?.dateTo,
            run_source: 'ci',
            statuses: 'failed',
        })
        expect(list.mock.calls.at(-1)?.[1]?.cursor).toBeUndefined()
        expect(router.values.searchParams.cursor_stack).toBeUndefined()
        expect(readOfflineScorerPreferences(props.userId, props.teamId)).toEqual(saved)

        router.actions.push(urls.aiObservabilityOfflineEvaluationExperiment(overviewExperiments[0].id))
        router.actions.locationChanged({
            method: 'POP',
            pathname: listUrl.pathname,
            search: listUrl.search,
            searchParams: listSearch,
            hash: '',
            hashParams: {},
            url: listUrl.url,
        })
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.cursorStack).toEqual(['cursor-2'])
        expect(logic.values.dateRange).toEqual(initialRange)
        expect(logic.values.trendFilters).toEqual({ run_source: 'local', statuses: 'uploading' })
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: initialRange?.dateFrom,
            date_to: initialRange?.dateTo,
            cursor: 'cursor-2',
            run_source: 'local',
            statuses: 'uploading',
        })
    })

    it.each([true, false])(
        'distinguishes no matching experiments from a new project (has history: %s)',
        async (hasHistory) => {
            const emptyPage: OfflineExperimentPageApi = { results: [], count: 0, next_cursor: null }
            list.mockResolvedValueOnce(emptyPage).mockResolvedValueOnce(hasHistory ? page : emptyPage)
            const logic = offlineExperimentsLogic(props)
            logic.mount()
            await jest.advanceTimersByTimeAsync(150)

            expect(logic.values.experiments).toEqual(emptyPage)
            expect(logic.values.hasExperiments).toBe(hasHistory)
            expect(list).toHaveBeenLastCalledWith(String(props.teamId), { limit: 1 })
        }
    )

    it('keeps onboarding hidden when the project presence check fails', async () => {
        list.mockResolvedValueOnce({ results: [], count: 0, next_cursor: null }).mockRejectedValueOnce(
            new Error('Unavailable')
        )
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)

        expect(logic.values.hasExperiments).toBeNull()
        expect(logic.values.experimentsError).not.toBeNull()
    })

    it('drops a stale failed list request after a newer filtered page succeeds', async () => {
        let rejectOld: (error: Error) => void = () => {}
        list.mockReturnValueOnce(
            new Promise((_, reject) => {
                rejectOld = reject
            })
        )
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        logic.actions.setFilters({ search: 'latest' })
        await jest.advanceTimersByTimeAsync(150)
        rejectOld(new Error('An older request failed'))
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.experiments).toEqual(page)
        expect(logic.values.experimentsError).toBeNull()
        expect(logic.values.experimentsLoading).toBe(false)
    })

    it('rejects invalid shared dates without loading experiments or charts', async () => {
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), { scores: '', date_from: 'invalid-date' })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        expect(list).not.toHaveBeenCalled()
        expect(logic.values.experimentsError).toBe('Choose a valid experiment date range.')
        expect(logic.values.dateRange).toBeNull()
        expect(logic.values.hasExperiments).toBeNull()

        logic.actions.setFilters({ date_from: '-30d' })
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.experiments).toEqual(page)
        expect(logic.values.experimentsError).toBeNull()
        expect(logic.values.dateRange).not.toBeNull()
        expect(logic.values.trendFilters).toEqual({ statuses: 'completed,uploading,failed' })
        expect(logic.values.hasExperiments).toBe(true)
        expect(logic.values.scorerIds).toEqual(overviewScorers.map(({ id }) => id))
    })
})

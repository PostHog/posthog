import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineExperimentPageApi } from '../generated/api.schemas'
import { offlineExperimentsLogic } from './offlineExperimentsLogic'
import { overviewExperiments, overviewScorers } from './offlineOverviewFixtures'
import { readOfflineScorerPreferences, saveOfflineScorerPreferences } from './offlineOverviewState'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsList: jest.fn(),
    aiObservabilityOfflineExperimentsScorerSummariesList: jest.fn(),
    llmAnalyticsScoreDefinitionsList: jest.fn(),
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
        jest.mocked(api.llmAnalyticsScoreDefinitionsList).mockResolvedValue({
            results: overviewScorers,
            count: 3,
            next: null,
            previous: null,
        })
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), { scores: '' })
    })

    afterEach(() => jest.useRealTimers())

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

    it('keeps trend filters separate from list pagination and preferences, and restores both filters on Back', async () => {
        const saved = [overviewScorers[0].id]
        saveOfflineScorerPreferences(props.userId, props.teamId, saved)
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), {
            scores: '',
            date_from: '-24h',
            run_source: 'local',
            suite_key: 'list-suite',
        })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        const initialRange = list.mock.calls.at(-1)?.[1]
        const initialTrendRange = logic.values.trendRange
        logic.actions.nextPage('cursor-2')
        await jest.advanceTimersByTimeAsync(150)

        jest.setSystemTime(new Date('2026-09-28T15:00:00Z'))
        const trendFilters = {
            run_source: 'ci',
            suite_key: 'trend-suite',
            dataset_source: 'local',
            dataset_identifier: 'sample-set',
            dataset_revision_identifier: 'revision-2',
        }
        logic.actions.setTrendFilters(trendFilters)
        await jest.advanceTimersByTimeAsync(150)
        expect(list).toHaveBeenCalledTimes(2)
        expect(logic.values.cursorStack).toEqual(['cursor-2'])
        expect(logic.values.trendRange).toEqual(initialTrendRange)
        expect(readOfflineScorerPreferences(props.userId, props.teamId)).toEqual(saved)
        expect(router.values.searchParams).toMatchObject({
            run_source: 'local',
            suite_key: 'list-suite',
            trend_run_source: 'ci',
            trend_suite_key: 'trend-suite',
            trend_dataset_source: 'local',
            trend_dataset_identifier: 'sample-set',
            trend_dataset_revision_identifier: 'revision-2',
        })
        const listUrl = combineUrl(router.values.location.pathname, router.values.searchParams)
        const listSearch = { ...router.values.searchParams }

        logic.actions.setTrendDates('-7d', null)
        logic.actions.setTrendFilters({ suite_key: undefined })
        expect(router.values.searchParams.trend_suite_key).toBeUndefined()
        logic.actions.nextPage('cursor-3')
        await jest.advanceTimersByTimeAsync(150)
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: initialRange?.date_from,
            date_to: initialRange?.date_to,
            cursor: 'cursor-3',
            run_source: 'local',
            suite_key: 'list-suite',
        })
        expect(list.mock.calls.at(-1)?.[1]?.dataset_identifier).toBeUndefined()

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
        expect(logic.values.trendFilters).toEqual(trendFilters)
        expect(list.mock.calls.at(-1)?.[1]).toMatchObject({
            date_from: initialRange?.date_from,
            date_to: initialRange?.date_to,
            cursor: 'cursor-2',
        })

        logic.actions.setFilters({ run_source: 'ci' })
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.cursorStack).toEqual([])
        expect(list.mock.calls.at(-1)?.[1]?.cursor).toBeUndefined()
        expect(router.values.searchParams.cursor_stack).toBeUndefined()
        expect(logic.values.trendFilters).toEqual(trendFilters)
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

    it('reports invalid list dates without issuing a request and keeps invalid trend dates independent', async () => {
        router.actions.push(urls.aiObservabilityOfflineEvaluations(), { scores: '', date_from: 'invalid-date' })
        const logic = offlineExperimentsLogic(props)
        logic.mount()
        await jest.advanceTimersByTimeAsync(150)
        expect(list).not.toHaveBeenCalled()
        expect(logic.values.experimentsError).toBe('Choose a valid experiment date range.')

        logic.actions.setFilters({ date_from: undefined })
        logic.actions.setTrendDates('invalid-date', null)
        await jest.advanceTimersByTimeAsync(150)
        expect(logic.values.experiments).toEqual(page)
        expect(logic.values.experimentsError).toBeNull()
        expect(logic.values.trendRange).toBeNull()
    })
})

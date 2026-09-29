import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineHistoryPageApi } from '../generated/api.schemas'
import { offlineExperimentsLogic } from './offlineExperimentsLogic'
import { overviewScorers, overviewHistory } from './offlineOverviewFixtures'
import { offlineOverviewTrendLogic } from './offlineOverviewTrendLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    aiObservabilityOfflineScorersHistoryList: jest.fn(),
    aiObservabilityOfflineExperimentsList: jest.fn(),
}))

const props = {
    teamId: 997,
    scorerId: overviewScorers[0].id,
    dateFrom: '2026-09-01T00:00:00Z',
    dateTo: '2026-09-28T00:00:00Z',
    refreshKey: 0,
}
const page: OfflineHistoryPageApi = { results: overviewHistory(overviewScorers[0]), count: 100, next_cursor: 'older' }
const retrieve = jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve)
const history = jest.mocked(api.aiObservabilityOfflineScorersHistoryList)

function mountOverview(): ReturnType<typeof offlineExperimentsLogic.build> {
    router.actions.push(urls.aiObservabilityOfflineEvaluations(), {
        scores: props.scorerId,
        date_from: 'all',
        date_to: props.dateTo,
    })
    const logic = offlineExperimentsLogic({ teamId: props.teamId, userId: 1, timezone: 'UTC' })
    logic.mount()
    return logic
}

describe('offlineOverviewTrendLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        retrieve.mockResolvedValue(overviewScorers[0])
        history.mockResolvedValue(page)
        jest.mocked(api.aiObservabilityOfflineExperimentsList).mockResolvedValue({
            results: [],
            count: 0,
            next_cursor: null,
        })
    })

    it('does not query history for a remembered scorer that is no longer accessible', async () => {
        retrieve.mockRejectedValueOnce(new Error('Not found'))
        const unavailable = offlineOverviewTrendLogic(props)
        unavailable.mount()
        await expectLogic(unavailable).toFinishAllListeners()
        expect(unavailable.values.trend).toBeNull()
        expect(unavailable.values.trendError).toBe(true)
        expect(history).not.toHaveBeenCalled()

        const accessible = offlineOverviewTrendLogic({ ...props, scorerId: overviewScorers[1].id })
        accessible.mount()
        await expectLogic(accessible).toFinishAllListeners()
        expect(accessible.values.trend?.page).toEqual(page)
        expect(accessible.values.trendError).toBe(false)
    })

    it.each(['failed', 'successful'])(
        'does not let an older %s history request replace a newer window or its shared bounds',
        async (outcome) => {
            const overviewLogic = mountOverview()
            const trendProps = {
                ...props,
                dateFrom: undefined,
                overviewLogic,
                trendQueryKey: overviewLogic.values.trendQueryKey,
            }
            let finishOld: () => void = () => {}
            let markRequestStarted: () => void = () => {}
            const requestStarted = new Promise<void>((resolve) => {
                markRequestStarted = resolve
            })
            history.mockImplementationOnce(() => {
                markRequestStarted()
                return new Promise((resolve, reject) => {
                    finishOld = () =>
                        outcome === 'failed'
                            ? reject(new Error('An older date window failed'))
                            : resolve({
                                  ...page,
                                  results: page.results.map((point) => ({
                                      ...point,
                                      experiment: { ...point.experiment, started_at: '2020-01-01T00:00:00Z' },
                                  })),
                              })
                })
            })
            const logic = offlineOverviewTrendLogic(trendProps)
            logic.mount()
            await requestStarted
            overviewLogic.actions.setFilters({ run_source: 'ci' })
            offlineOverviewTrendLogic({
                ...trendProps,
                filters: overviewLogic.values.trendFilters,
                trendQueryKey: overviewLogic.values.trendQueryKey,
            })
            await expectLogic(logic).toDispatchActions(['loadOfflineOverviewTrendSuccess'])
            finishOld()
            await expectLogic(logic).toFinishAllListeners()

            expect(history).toHaveBeenLastCalledWith(
                '997',
                props.scorerId,
                expect.objectContaining({
                    date_from: undefined,
                    run_source: 'ci',
                    statuses: 'completed,uploading,failed',
                })
            )
            expect(logic.values.trend?.page).toEqual(page)
            expect(logic.values.trendError).toBe(false)
            expect(logic.values.trendLoading).toBe(false)
            expect(overviewLogic.values.trendXDomain).toEqual([
                Math.min(...page.results.map(({ experiment }) => Date.parse(experiment.started_at))),
                Date.parse(props.dateTo),
            ])
        }
    )

    it('shows one version at a time and falls back when it has no results in the new window', async () => {
        const overviewLogic = mountOverview()
        const trendProps = {
            ...props,
            dateFrom: undefined,
            overviewLogic,
            trendQueryKey: overviewLogic.values.trendQueryKey,
        }
        const olderPoints = page.results.map((point) => ({
            ...point,
            experiment: { ...point.experiment, started_at: '2026-08-01T00:00:00Z' },
            summary: { ...point.summary, scorer: { ...point.summary.scorer, id: 'older-version', version: 1 } },
        }))
        history.mockResolvedValueOnce({ ...page, results: [...olderPoints, ...page.results] })
        const logic = offlineOverviewTrendLogic(trendProps)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeVersion?.version).toBe(2)
        expect(logic.values.versionPoints).toEqual(page.results)
        const sharedDomain = [Date.parse('2026-08-01T00:00:00Z'), Date.parse(props.dateTo)]
        expect(overviewLogic.values.trendXDomain).toEqual(sharedDomain)
        logic.actions.selectVersion('older-version')
        expect(logic.values.versionPoints).toEqual(olderPoints)
        expect(overviewLogic.values.trendXDomain).toEqual(sharedDomain)

        overviewLogic.actions.setFilters({ date_from: '2026-09-20T00:00:00Z' })
        offlineOverviewTrendLogic({
            ...trendProps,
            dateFrom: '2026-09-20T00:00:00Z',
            trendQueryKey: overviewLogic.values.trendQueryKey,
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.activeVersion?.version).toBe(2)
        expect(logic.values.versionPoints).toEqual(page.results)
    })

    it('reloads a shared source and upload state within the same frozen date range', async () => {
        const logic = offlineOverviewTrendLogic({ ...props, filters: { run_source: 'local' } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const filters = { run_source: 'ci', statuses: 'failed' }
        offlineOverviewTrendLogic({ ...props, filters })
        await expectLogic(logic).toFinishAllListeners()

        expect(history).toHaveBeenCalledTimes(2)
        expect(history).toHaveBeenLastCalledWith('997', props.scorerId, {
            ...filters,
            date_from: props.dateFrom,
            date_to: props.dateTo,
            limit: 100,
        })
    })
})

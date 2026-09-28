import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineHistoryPageApi } from '../generated/api.schemas'
import { overviewScorers, overviewHistory } from './offlineOverviewFixtures'
import { offlineOverviewTrendLogic } from './offlineOverviewTrendLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    aiObservabilityOfflineScorersHistoryList: jest.fn(),
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

describe('offlineOverviewTrendLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        retrieve.mockResolvedValue(overviewScorers[0])
        history.mockResolvedValue(page)
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

    it('does not let an older failed history request replace a newer successful date window', async () => {
        let rejectOld: (error: Error) => void = () => {}
        let markRequestStarted: () => void = () => {}
        const requestStarted = new Promise<void>((resolve) => {
            markRequestStarted = resolve
        })
        history.mockImplementationOnce(() => {
            markRequestStarted()
            return new Promise((_, reject) => {
                rejectOld = reject
            })
        })
        const logic = offlineOverviewTrendLogic(props)
        logic.mount()
        await requestStarted
        offlineOverviewTrendLogic({ ...props, dateFrom: '2026-09-20T00:00:00Z' })
        await expectLogic(logic).toDispatchActions(['loadOfflineOverviewTrendSuccess'])
        rejectOld(new Error('An older date window failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(history).toHaveBeenLastCalledWith(
            '997',
            props.scorerId,
            expect.objectContaining({ date_from: '2026-09-20T00:00:00Z', statuses: 'completed' })
        )
        expect(logic.values.trend?.page).toEqual(page)
        expect(logic.values.trendError).toBe(false)
        expect(logic.values.trendLoading).toBe(false)
    })

    it('reloads a changed trend cohort within the same frozen date range', async () => {
        const logic = offlineOverviewTrendLogic({ ...props, filters: { run_source: 'local' } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const filters = { run_source: 'ci', suite_key: 'trend-suite', dataset_identifier: 'sample-set' }
        offlineOverviewTrendLogic({ ...props, filters })
        await expectLogic(logic).toFinishAllListeners()

        expect(history).toHaveBeenCalledTimes(2)
        expect(history).toHaveBeenLastCalledWith('997', props.scorerId, {
            ...filters,
            date_from: props.dateFrom,
            date_to: props.dateTo,
            statuses: 'completed',
            limit: 100,
        })
    })
})

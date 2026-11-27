import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { offlineComparisonLogic } from './offlineComparisonLogic'
import { overviewExperiments } from './offlineOverviewFixtures'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsScorerSummariesList: jest.fn(),
}))

const detail = jest.mocked(api.aiObservabilityOfflineExperimentsRetrieve)
const summaries = jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList)
const experimentIds = overviewExperiments.slice(0, 5).map(({ id }) => id)
const props = { teamId: 997, experimentIds }
const page = { count: 0, results: [], next: null, previous: null, next_cursor: null }

describe('offlineComparisonLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        detail.mockImplementation(async (_, id) => overviewExperiments.find((run) => run.id === id)!)
        summaries.mockResolvedValue(page)
    })

    it('finishes each run once when the baseline changes during a load', async () => {
        let release!: () => void
        const slow = new Promise<void>((resolve) => {
            release = resolve
        })
        summaries.mockImplementation(async () => {
            await slow
            return page
        })
        const logic = offlineComparisonLogic(props)
        logic.mount()
        await waitFor(() => expect(summaries).toHaveBeenCalledTimes(4))
        const reordered = offlineComparisonLogic({ ...props, experimentIds: [...experimentIds].reverse() })
        expect(reordered).toBe(logic)
        release()
        await expectLogic(logic).toFinishAllListeners()
        expect(detail.mock.calls.map(([, id]) => id).sort()).toEqual([...experimentIds].sort())
        expect(Object.keys(logic.values.results!).sort()).toEqual([...experimentIds].sort())
    })

    it('keeps successful runs and retries only the run whose summaries failed', async () => {
        summaries.mockRejectedValueOnce(new ApiError('Narrow the filters and try again.', 503))
        const logic = offlineComparisonLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const failedId = experimentIds[0]
        expect(logic.values.results?.[failedId]).toMatchObject({
            name: overviewExperiments[0].name,
            error: expect.stringContaining('timed out'),
        })
        expect(logic.values.results?.[experimentIds[1]]).toHaveProperty('experiment')
        detail.mockClear()
        logic.actions.loadComparison()
        await expectLogic(logic).toFinishAllListeners()
        expect(detail.mock.calls.map(([, id]) => id)).toEqual([failedId])
        expect(logic.values.results?.[failedId]).toHaveProperty('experiment')
    })
})

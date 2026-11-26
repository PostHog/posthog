import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { businessKnowledgeSourcesUsageRetrieve } from '../../generated/api'
import type { KnowledgeUsageApi } from '../../generated/api.schemas'
import { businessKnowledgeUsageLogic } from './businessKnowledgeUsageLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
}))

jest.mock('../../generated/api', () => ({
    businessKnowledgeSourcesUsageRetrieve: jest.fn(),
}))

const mockedUsage = businessKnowledgeSourcesUsageRetrieve as jest.Mock

const usage: KnowledgeUsageApi = {
    days: 30,
    cited_run_count: 3,
    learned_cited_run_count: 1,
    source_count: 4,
    cited_source_count: 2,
    chunks_ingested: 40,
    query_count: 9,
    chunks_by_surface: [{ surface: 'url', total: 40 }],
    queries_by_surface: [{ surface: 'api', total: 9 }],
    daily: [
        { date: '2026-05-19', cited_run_count: 1, chunks_ingested: 40, query_count: 4 },
        { date: '2026-05-20', cited_run_count: 2, chunks_ingested: 0, query_count: 5 },
    ],
    top_sources: [],
}

describe('businessKnowledgeUsageLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeUsageLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        initKeaTests()
        mockedUsage.mockResolvedValue(usage)
        logic = businessKnowledgeUsageLogic()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('loads the chosen period again when the period changes', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dailyCounts).toEqual([1, 2])
        expect(logic.values.dailyLabels).toEqual(['May 19', 'May 20'])
        expect(logic.values.dailyChunks).toEqual([40, 0])
        expect(logic.values.dailyQueries).toEqual([4, 5])

        logic.actions.setDays(7)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedUsage.mock.calls.map(([, params]) => params)).toEqual([{ days: 30 }, { days: 7 }])
    })

    it.each([
        ['an older result', (resolve: (value: KnowledgeUsageApi) => void) => resolve({ ...usage, days: 30 })],
        ['an older failure', (_: unknown, reject: (reason: Error) => void) => reject(new Error('boom'))],
    ])('ignores %s that arrives after the newer period loaded', async (_name, settleOlder) => {
        let settleFirst: () => void = () => {}
        mockedUsage.mockImplementationOnce(
            () =>
                new Promise<KnowledgeUsageApi>((resolve, reject) => {
                    settleFirst = () => settleOlder(resolve, reject)
                })
        )
        mockedUsage.mockResolvedValueOnce({ ...usage, days: 7 })
        logic.mount()

        logic.actions.setDays(7)
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess'])
        settleFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.usage?.days).toBe(7)
        expect(logic.values.usageLoadFailed).toBe(false)
    })

    it('reports a failed load until the next load succeeds', async () => {
        mockedUsage.mockRejectedValueOnce(new Error('boom'))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.usageLoadFailed).toBe(true)
        expect(logic.values.usage).toBeNull()

        logic.actions.loadUsage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.usageLoadFailed).toBe(false)
        expect(logic.values.usage).toEqual(usage)
    })
})

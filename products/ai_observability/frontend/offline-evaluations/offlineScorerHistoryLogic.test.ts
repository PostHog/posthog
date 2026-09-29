import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { offlineScorerHistoryLogic, offlineScorerHistoryUrl } from './offlineScorerHistoryLogic'
import { OFFLINE_STORY_DEFINITION, OFFLINE_STORY_VERSION, makeOfflineHistoryPoint } from './offlineScoreTrends.fixtures'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    llmAnalyticsScoreDefinitionsVersionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsVersionsRetrieve: jest.fn(),
    aiObservabilityOfflineScorersHistoryList: jest.fn(),
}))

describe('offlineScorerHistoryLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockResolvedValue(OFFLINE_STORY_DEFINITION)
        jest.mocked(api.llmAnalyticsScoreDefinitionsVersionsList).mockResolvedValue({
            results: [OFFLINE_STORY_VERSION],
            next_cursor: null,
            count: 1,
        })
        jest.mocked(api.llmAnalyticsScoreDefinitionsVersionsRetrieve).mockResolvedValue(OFFLINE_STORY_VERSION)
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockResolvedValue({
            results: [makeOfflineHistoryPoint(1)],
            next_cursor: 'older',
            count: 150,
        })
    })

    it('keeps the periods cursors independent and freezes both resolved windows while paging', async () => {
        const logic = offlineScorerHistoryLogic({ scorerId: OFFLINE_STORY_DEFINITION.id, teamId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () =>
            logic.actions.setFilters({ compare: 'previous', date_from: '-24h' })
        ).toFinishAllListeners()
        const windows = logic.values.windows
        await expectLogic(logic, () => logic.actions.changePage('comparison', 'older')).toFinishAllListeners()
        expect(logic.values.primaryCursors).toEqual([null])
        expect(logic.values.comparisonCursors).toEqual([null, 'older'])
        expect(logic.values.windows).toEqual(windows)
        expect(jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mock.calls.at(-1)?.[2]).toMatchObject({
            cursor: 'older',
            scorer_version_ids: OFFLINE_STORY_VERSION.id,
            date_from: windows.comparison!.dateFrom,
            date_to: windows.comparison!.dateTo,
        })
        await expectLogic(logic, () => logic.actions.setFilters({ run_source: 'ci' })).toFinishAllListeners()
        expect(logic.values.primaryCursors).toEqual([null])
        expect(logic.values.comparisonCursors).toEqual([null])
    })

    it('uses a bookmarked exact historical version even when the first discovery page does not include it', async () => {
        router.actions.push(`/ai-evals/evaluations/scorers/${OFFLINE_STORY_DEFINITION.id}/offline`, {
            version: 'older-version',
            date_from: '2026-01-01',
            date_to: '2026-01-10',
        })
        jest.mocked(api.llmAnalyticsScoreDefinitionsVersionsRetrieve).mockResolvedValue({
            ...OFFLINE_STORY_VERSION,
            id: 'older-version',
            version: 1,
        })
        const logic = offlineScorerHistoryLogic({ scorerId: OFFLINE_STORY_DEFINITION.id, teamId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.version).toBe('older-version')
        expect(jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mock.calls.at(-1)?.[0]).toBe('1')
        expect(logic.values.versionOptions).toContainEqual({ value: 'older-version', label: 'Version 1' })
        expect(
            jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mock.calls.at(-1)?.[2]?.scorer_version_ids
        ).toBe('older-version')
    })

    it.each([
        ['uploading', 5],
        ['failed', 45],
        ['completed', 45],
    ] as const)(
        'includes %s experiments started %i days ago when opened from their scorer link',
        async (status, age) => {
            const startedAt = dayjs().subtract(age, 'day').toISOString()
            router.actions.push(
                offlineScorerHistoryUrl(
                    { id: OFFLINE_STORY_VERSION.id, definition_id: OFFLINE_STORY_DEFINITION.id },
                    { status, started_at: startedAt },
                    'UTC'
                )
            )
            const logic = offlineScorerHistoryLogic({ scorerId: OFFLINE_STORY_DEFINITION.id, teamId: 1 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const query = jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mock.calls.at(-1)?.[2]
            expect(query?.scorer_version_ids).toBe(OFFLINE_STORY_VERSION.id)
            expect(query?.statuses?.split(',')).toContain(status)
            expect(dayjs(query?.date_from).isAfter(startedAt)).toBe(false)
        }
    )

    it('keeps a newer history response when a superseded request rejects', async () => {
        const logic = offlineScorerHistoryLogic({ scorerId: OFFLINE_STORY_DEFINITION.id, teamId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let rejectOld!: (error: Error) => void
        let markStarted!: () => void
        const started = new Promise<void>((resolve) => {
            markStarted = resolve
        })
        const old = new Promise<never>((_, reject) => {
            rejectOld = reject
        })
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockImplementationOnce(() => {
            markStarted()
            return old
        })
        logic.actions.loadOfflineHistoryPrimaryPage()
        await started
        const newest = { results: [makeOfflineHistoryPoint(3)], next_cursor: null, count: 1 }
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockResolvedValueOnce(newest)
        await expectLogic(logic, () => logic.actions.loadOfflineHistoryPrimaryPage()).toDispatchActions([
            'loadOfflineHistoryPrimaryPageSuccess',
        ])
        rejectOld(new Error('Earlier request failed'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.primaryPage).toEqual(newest)
        expect(logic.values.primaryError).toBeNull()
    })
})

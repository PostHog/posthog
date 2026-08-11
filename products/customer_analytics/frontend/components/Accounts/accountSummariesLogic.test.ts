import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsPartialUpdate,
    accountsRetrieve,
    accountsSummariesList,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, AccountChannelSummaryApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { periodLabel } from './AccountSummariesExpansion'
import { accountSummariesLogic, FIRST_SUMMARY_POLL_TIMEOUT_MS, FIRST_SUMMARY_QUIET_MS } from './accountSummariesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsRetrieve: jest.fn(),
    accountsSummariesList: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const mockRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>
const mockList = accountsSummariesList as jest.MockedFunction<typeof accountsSummariesList>
const mockPatch = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>

const ACCOUNT = {
    properties: { slack_channel_id: 'C123' },
    slack_summary_cadence: 'weekly',
} as unknown as AccountApi

const CADENCE_OFF = { ...ACCOUNT, slack_summary_cadence: null } as unknown as AccountApi

const SUMMARY = { id: 's-1', cadence: 'weekly', content: '## What happened' } as AccountChannelSummaryApi

describe('accountSummariesLogic', () => {
    let logic: ReturnType<typeof accountSummariesLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        // Clears this account's module-level backfill deadline, which would leak into the next test.
        logic?.actions.stopFirstSummaryPolling()
        logic?.unmount()
    })

    const mount = async (accountId = 'acc-1'): Promise<void> => {
        logic = accountSummariesLogic({ accountId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('loads the account channel binding, cadence, and first page of summaries', async () => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 12, next: null, previous: null, results: [SUMMARY] })

        await mount()

        expect(logic.values.summariesResult).toEqual({
            summaries: [SUMMARY],
            totalCount: 12,
            slackChannelId: 'C123',
            cadence: 'weekly',
        })
    })

    it('loadSummariesPage fetches by offset and replaces the current page', async () => {
        const OLDER = { id: 's-2', cadence: 'weekly', content: '## Older' } as AccountChannelSummaryApi
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 12, next: null, previous: null, results: [SUMMARY] })
        await mount()
        mockList.mockResolvedValue({ count: 12, next: null, previous: null, results: [OLDER] })

        logic.actions.loadSummariesPage({ page: 2 })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', { limit: 5, offset: 5 })
        expect(logic.values.summariesResult.summaries).toEqual([OLDER])
        expect(logic.values.page).toBe(2)
    })

    it('surfaces a load-failed result (not an infinite skeleton) and captures the error', async () => {
        mockRetrieve.mockRejectedValue(new Error('network'))
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })

        await mount()

        expect(logic.values.summariesResult.loadFailed).toBe(true)
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })

    it('setCadence patches the account, updates the value, and resets the saving flag', async () => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(ACCOUNT)
        await mount()

        logic.actions.setCadence('monthly')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockPatch).toHaveBeenCalledWith(expect.any(String), 'acc-1', { slack_summary_cadence: 'monthly' })
        expect(logic.values.summariesResult.cadence).toBe('monthly')
        expect(logic.values.cadenceSaving).toBe(false)
    })

    it('watches for the backfilled summaries after turning summaries on', async () => {
        mockRetrieve.mockResolvedValue(CADENCE_OFF)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(CADENCE_OFF)
        await mount()

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generatingFirstSummary).toBe(true)

        mockList.mockResolvedValue({ count: 1, next: null, previous: null, results: [SUMMARY] })
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.summariesResult.summaries).toEqual([SUMMARY])
    })

    it('resumes the wait after the account row is collapsed and re-expanded', async () => {
        mockRetrieve.mockResolvedValue(CADENCE_OFF)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(CADENCE_OFF)
        await mount('acc-collapse')

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        await mount('acc-collapse')

        expect(logic.values.generatingFirstSummary).toBe(true)
    })

    it('keeps waiting while summaries are still arriving, then stops when the backfill goes quiet', async () => {
        mockRetrieve.mockResolvedValue(CADENCE_OFF)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(CADENCE_OFF)
        await mount('acc-daily')
        const startedAt = Date.now()
        const nowSpy = jest.spyOn(Date, 'now')

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()

        for (const count of [3, 6]) {
            nowSpy.mockReturnValue(startedAt + FIRST_SUMMARY_QUIET_MS * 2)
            mockList.mockResolvedValue({ count, next: null, previous: null, results: [SUMMARY] })
            logic.actions.loadSummaries()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.generatingFirstSummary).toBe(true)
        }

        nowSpy.mockReturnValue(startedAt + FIRST_SUMMARY_QUIET_MS * 3 + 1)
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.generatingFirstSummary).toBe(false)
        nowSpy.mockRestore()
    })

    it('stops waiting at the deadline even when no summary ever lands', async () => {
        mockRetrieve.mockResolvedValue(CADENCE_OFF)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(CADENCE_OFF)
        await mount('acc-deadline')
        const startedAt = Date.now()
        const nowSpy = jest.spyOn(Date, 'now')

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generatingFirstSummary).toBe(true)

        nowSpy.mockReturnValue(startedAt + FIRST_SUMMARY_POLL_TIMEOUT_MS + 1)
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.generatingFirstSummary).toBe(false)
        nowSpy.mockRestore()
    })

    it.each([
        ['the account already has summaries', [SUMMARY], 'daily' as const],
        ['summaries are being turned off', [], null],
        // ACCOUNT starts on 'weekly', and only an off-to-on switch backfills.
        ['switching between two enabled cadences', [], 'daily' as const],
    ])('does not poll when %s', async (_name, results, cadence) => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: results.length, next: null, previous: null, results })
        mockPatch.mockResolvedValue(ACCOUNT)
        await mount()

        logic.actions.setCadence(cadence)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.generatingFirstSummary).toBe(false)
    })

    it.each([
        ['2026-07-27T00:00:00Z', '2026-07-28T00:00:00Z', '2026-07-27'],
        ['2026-07-21T00:00:00Z', '2026-07-28T15:30:00Z', '2026-07-21 to 2026-07-28'],
    ])('labels a daily summary spanning %s to %s as "%s"', (period_start, period_end, expected) => {
        expect(periodLabel({ ...SUMMARY, cadence: 'daily', period_start, period_end })).toBe(expected)
    })

    it('a failed cadence save keeps the previous cadence and resets the saving flag', async () => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockRejectedValue(new Error('nope'))
        await mount()

        logic.actions.setCadence(null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.summariesResult.cadence).toBe('weekly')
        expect(logic.values.cadenceSaving).toBe(false)
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })
})

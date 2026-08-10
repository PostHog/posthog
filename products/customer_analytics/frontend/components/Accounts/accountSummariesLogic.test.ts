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
import { accountSummariesLogic } from './accountSummariesLogic'

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
        logic?.unmount()
    })

    // Account id is a parameter because the in-flight backfill deadlines are module state,
    // so a test that leaves one pending would otherwise bleed into the next.
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

    it('watches for the backfilled first summary after turning summaries on, and stops once it lands', async () => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(ACCOUNT)
        await mount()

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generatingFirstSummary).toBe(true)

        // What the poll's interval does once the backfill lands.
        mockList.mockResolvedValue({ count: 1, next: null, previous: null, results: [SUMMARY] })
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.summariesResult.summaries).toEqual([SUMMARY])
        expect(logic.values.generatingFirstSummary).toBe(false)
    })

    it('resumes the wait after the account row is collapsed and re-expanded', async () => {
        mockRetrieve.mockResolvedValue(ACCOUNT)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(ACCOUNT)
        await mount('acc-collapse')

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        await mount('acc-collapse')

        expect(logic.values.generatingFirstSummary).toBe(true)
    })

    it('keeps waiting until every daily summary lands, not just the first', async () => {
        const daily = { ...ACCOUNT, slack_summary_cadence: 'daily' } as AccountApi
        mockRetrieve.mockResolvedValue(daily)
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockPatch.mockResolvedValue(daily)
        await mount('acc-daily')

        logic.actions.setCadence('daily')
        await expectLogic(logic).toFinishAllListeners()

        // count, not results length: a page holds 5 and the backfill writes 7.
        mockList.mockResolvedValue({ count: 3, next: null, previous: null, results: [SUMMARY] })
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generatingFirstSummary).toBe(true)

        mockList.mockResolvedValue({ count: 7, next: null, previous: null, results: [SUMMARY] })
        logic.actions.loadSummaries()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generatingFirstSummary).toBe(false)
    })

    it.each([
        ['the account already has summaries', [SUMMARY], 'daily' as const],
        ['summaries are being turned off', [], null],
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

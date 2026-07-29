import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsPartialUpdate,
    accountsRetrieve,
    accountsSummariesList,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, AccountChannelSummaryApi } from 'products/customer_analytics/frontend/generated/api.schemas'

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

    const mount = async (): Promise<void> => {
        logic = accountSummariesLogic({ accountId: 'acc-1' })
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

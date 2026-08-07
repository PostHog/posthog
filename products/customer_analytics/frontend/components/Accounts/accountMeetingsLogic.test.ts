import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsMeetingsList,
    accountsPartialUpdate,
    accountsRetrieve,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, MeetingApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountMeetingsLogic } from './accountMeetingsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsMeetingsList: jest.fn(),
    accountsRetrieve: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const mockList = accountsMeetingsList as jest.MockedFunction<typeof accountsMeetingsList>
const mockRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>
const mockPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>

describe('accountMeetingsLogic', () => {
    let logic: ReturnType<typeof accountMeetingsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        mockRetrieve.mockResolvedValue({ id: 'acc-1', properties: {} } as AccountApi)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountMeetingsLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('loads the account meetings', async () => {
        const meetings = [{ id: 'm-1', title: 'Kickoff', status: 'confirmed' }] as MeetingApi[]
        mockList.mockResolvedValue(meetings)

        await mount()

        expect(logic.values.meetingsResult).toEqual({ meetings })
    })

    it('surfaces a load-failed result (not an infinite skeleton) and captures the error when the fetch throws', async () => {
        mockList.mockRejectedValue(new Error('network'))

        await mount()

        expect(logic.values.meetingsResult).toEqual({ meetings: null, loadFailed: true })
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })

    it('filters meetings by title or attendee, case-insensitively', async () => {
        const meetings = [
            { id: 'm-1', title: 'Quarterly review', participants: [{ email: 'jane@acme.com', display_name: 'Jane' }] },
            { id: 'm-2', title: 'Kickoff', participants: [{ email: 'bob@other.com', display_name: 'Bob' }] },
        ] as unknown as MeetingApi[]
        mockList.mockResolvedValue(meetings)

        await mount()

        logic.actions.setSearchTerm('JANE')
        expect(logic.values.filteredMeetings.map((m) => m.id)).toEqual(['m-1'])
        logic.actions.setSearchTerm('kickoff')
        expect(logic.values.filteredMeetings.map((m) => m.id)).toEqual(['m-2'])
        logic.actions.setSearchTerm('')
        expect(logic.values.filteredMeetings).toHaveLength(2)
    })

    it('saves normalized matching values without clobbering other account properties', async () => {
        mockList.mockResolvedValue([])
        mockRetrieve.mockResolvedValue({
            id: 'acc-1',
            properties: { billing_id: 'cus_123', email_domains: ['old.com'] },
        } as AccountApi)
        mockPartialUpdate.mockResolvedValue({ id: 'acc-1', properties: {} } as AccountApi)

        await mount()
        logic.actions.setDomainsDraft(['@Acme.com', 'acme.com', ' '])
        logic.actions.setEmailsDraft(['Jane@Gmail.com'])
        logic.actions.saveMatching()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'acc-1', {
            properties: {
                billing_id: 'cus_123',
                email_domains: ['acme.com'],
                known_emails: ['jane@gmail.com'],
            },
        })
        expect(logic.values.matchingEditorOpen).toBe(false)
        expect(logic.values.savingMatching).toBe(false)
    })
})

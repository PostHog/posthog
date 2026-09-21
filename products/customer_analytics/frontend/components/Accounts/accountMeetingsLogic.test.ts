import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import {
    accountsMeetingsList,
    accountsPartialUpdate,
    accountsRetrieve,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, PaginatedMeetingListApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountMeetingsLogic, PAGE_SIZE } from './accountMeetingsLogic'

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

function pageOf(meetings: any[], count?: number): PaginatedMeetingListApi {
    return { results: meetings, count: count ?? meetings.length, next: null, previous: null }
}

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
        const meetings = [{ id: 'm-1', title: 'Kickoff', status: 'confirmed' }]
        mockList.mockResolvedValue(pageOf(meetings))

        await mount()

        expect(logic.values.meetingsResult).toEqual({ meetings, count: 1 })
    })

    it('surfaces a load-failed result (not an infinite skeleton) and captures the error when the fetch throws', async () => {
        mockList.mockRejectedValue(new Error('network'))

        await mount()

        expect(logic.values.meetingsResult).toEqual({ meetings: null, count: 0, loadFailed: true })
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })

    it('search resets to page 1 and reloads with the search param; paging sends the matching offset', async () => {
        mockList.mockResolvedValue(pageOf([], 25))
        await mount()

        logic.actions.setPage(3)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
            limit: PAGE_SIZE,
            offset: 2 * PAGE_SIZE,
            search: undefined,
        })

        logic.actions.setSearchTerm('jane')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
            limit: PAGE_SIZE,
            offset: 0,
            search: 'jane',
        })
    })

    it.each([
        [OrganizationMembershipLevel.Admin, true],
        [OrganizationMembershipLevel.Member, false],
    ])('allows membership level %s to edit meeting matching: %s', async (membershipLevel, expected) => {
        mockList.mockResolvedValue(pageOf([]))
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: membershipLevel,
            user_access_level: AccessControlLevel.Admin,
        })

        await mount()

        expect(logic.values.canEditMeetingMatching).toBe(expected)
    })

    it('saves normalized matching values without clobbering other account properties', async () => {
        mockList.mockResolvedValue(pageOf([]))
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

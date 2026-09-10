import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { searchLogic } from './searchLogic'

/** Poll until a condition holds. The searches settle in no fixed order, so an ordered
 *  `toDispatchActions` list would wait on an action that had already gone past. */
const waitFor = async (condition: () => boolean, timeoutMs = 4000): Promise<void> => {
    const deadline = Date.now() + timeoutMs
    while (!condition()) {
        if (Date.now() > deadline) {
            throw new Error('Timed out waiting for the other searches to settle')
        }
        await new Promise((resolve) => setTimeout(resolve, 25))
    }
}

describe('searchLogic', () => {
    let logic: ReturnType<typeof searchLogic.build>
    let personSearchCalls: { clientQueryId?: string; signal?: AbortSignal }[]
    let cancelledQueryIds: string[]
    let personListMock: jest.SpyInstance

    const neverResolvingPersonSearch = (): void => {
        personListMock.mockImplementation((params, options) => {
            personSearchCalls.push({ clientQueryId: params?.client_query_id, signal: options?.signal })
            return new Promise((_resolve, reject) => {
                options?.signal?.addEventListener('abort', () => {
                    reject(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }))
                })
            })
        })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/projects/:team_id/file_system/': { results: [], count: 0 },
                '/api/projects/:team_id/conversations/tickets/': { results: [], count: 0 },
            },
        })
        initKeaTests()

        personSearchCalls = []
        cancelledQueryIds = []
        personListMock = jest.spyOn(api.persons, 'list')
        jest.spyOn(api, 'cancelQuery').mockImplementation(async (clientQueryId: string) => {
            cancelledQueryIds.push(clientQueryId)
        })

        logic = searchLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('aborts and cancels the in-flight person search when the term is cleared', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        expect(personSearchCalls).toHaveLength(1)
        const { clientQueryId, signal } = personSearchCalls[0]
        expect(clientQueryId).toBeTruthy()
        expect(signal?.aborted).toBe(false)

        await expectLogic(logic, () => logic.actions.setSearch('')).toDispatchActions([
            'loadPersonSearchResultsFailure',
        ])
        expect(signal?.aborted).toBe(true)
        expect(cancelledQueryIds).toEqual([clientQueryId])
        expect(logic.values.personSearchResultsLoading).toBe(false)
    })

    it('cancels the previous person search on a new term without clearing the loading state', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        await expectLogic(logic, () => logic.actions.setSearch('alice b')).toDispatchActions([
            'loadPersonSearchResults',
        ])

        expect(personSearchCalls).toHaveLength(2)
        expect(personSearchCalls[0].signal?.aborted).toBe(true)
        expect(personSearchCalls[1].signal?.aborted).toBe(false)
        expect(cancelledQueryIds).toEqual([personSearchCalls[0].clientQueryId])

        // The superseded run must not settle the loader the newer run now owns.
        await expectLogic(logic).toNotHaveDispatchedActions(['loadPersonSearchResultsFailure'])
        expect(logic.values.personSearchResultsLoading).toBe(true)
    })

    it('maps matching support tickets into their own category', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [
                        {
                            id: '01890a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b',
                            ticket_number: 4321,
                            status: 'on_hold',
                            email_subject: 'Invoice looks wrong',
                            last_message_text: 'We were charged twice',
                        },
                    ],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('invoice')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])

        expect(logic.values.ticketItems).toEqual([
            expect.objectContaining({
                name: '#4321 Invoice looks wrong',
                category: 'tickets',
                href: urls.supportTicketDetail(4321),
                productCategory: 'On hold',
            }),
        ])
        expect(logic.values.allCategories.find((category) => category.key === 'tickets')?.items).toHaveLength(1)
    })

    // A Slack or widget ticket has no email subject, so the first message stands in as the title.
    it('falls back to the last message when a ticket has no subject', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [
                        {
                            id: '01890a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5c',
                            ticket_number: 77,
                            status: 'open',
                            email_subject: null,
                            last_message_text: 'Session replay is not recording',
                        },
                    ],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('replay')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])

        expect(logic.values.ticketItems[0].name).toBe('#77 Session replay is not recording')
    })

    // Free-text ticket search scans message content, so the palette must not send one per
    // keystroke while a query is still a letter or two long.
    it('does not search tickets until the query is long enough', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [{ id: 'ticket-uuid', ticket_number: 12, status: 'open', email_subject: 'Billing' }],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('bi')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])
        expect(logic.values.ticketItems).toEqual([])

        await expectLogic(logic, () => logic.actions.setSearch('bill')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])
        expect(logic.values.ticketItems).toHaveLength(1)
    })

    // Ticket search scans message content, so it is the slowest query in the palette and the one
    // most likely to still be in flight when the others settle. Leaving it out of `isSearching`
    // let the status line read "No results found" over a search that had not finished.
    it('still counts as searching while only tickets are in flight', async () => {
        personListMock.mockResolvedValue({ results: [] })
        // The mock team has group types, so the groups query would otherwise stay in flight and
        // hold `isSearching` true on its own, hiding the very thing under test.
        jest.spyOn(api.groups, 'listClickhouse').mockResolvedValue({ results: [], columns: [] } as any)
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => new Promise(() => {}),
            },
        })

        logic.actions.setSearch('billing')

        // Every other search has to have settled, or `isSearching` would be true for a reason
        // other than the one under test. They finish in no fixed order, so wait on the values.
        await waitFor(
            () =>
                !logic.values.searchPending &&
                !logic.values.searchedRecentsLoading &&
                !logic.values.unifiedSearchResultsLoading &&
                !logic.values.groupSearchResultsLoading &&
                !logic.values.personSearchResultsLoading &&
                !logic.values.playlistSearchResultsLoading
        )

        expect(logic.values.ticketSearchResultsLoading).toBe(true)
        expect(logic.values.isSearching).toBe(true)
    })

    it('does not cancel a person search that already returned', async () => {
        personListMock.mockResolvedValue({ results: [] })

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions([
            'loadPersonSearchResultsSuccess',
        ])
        await expectLogic(logic, () => logic.actions.setSearch('')).toFinishAllListeners()

        expect(cancelledQueryIds).toEqual([])
    })
})

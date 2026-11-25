import api from 'lib/api'

import { fileSystemSearchRetrieve } from '~/generated/core/api'
import { GroupTypeIndex, SearchResponse, SearchableEntity } from '~/types'

import { alertsList } from 'products/alerts/frontend/generated/api'
import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'
import { personsList } from 'products/persons/frontend/generated/api'
import { productToursList } from 'products/product_tours/frontend/generated/api'
import { hogFlowsList } from 'products/workflows/frontend/generated/api'

import { REMOTE_REQUESTS, RemoteContext, RemoteRequest, requestDebounceMs, settleRequest } from './commandKSources'

jest.mock('products/alerts/frontend/generated/api', () => ({ alertsList: jest.fn() }))
jest.mock('products/conversations/frontend/generated/api', () => ({ conversationsTicketsList: jest.fn() }))
jest.mock('products/persons/frontend/generated/api', () => ({ personsList: jest.fn() }))
jest.mock('products/product_tours/frontend/generated/api', () => ({ productToursList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({ hogFlowsList: jest.fn() }))
jest.mock('~/generated/core/api', () => ({
    ...jest.requireActual('~/generated/core/api'),
    fileSystemSearchRetrieve: jest.fn(),
}))

const context: RemoteContext = {
    currentTeamId: 1,
    groupTypes: [],
    aggregationLabel: () => ({ singular: 'organization', plural: 'organizations' }),
    customerAnalyticsEnabled: false,
}

const stalled: RemoteRequest = {
    id: 'persons',
    query: 'text',
    sources: ['persons'],
    fetch: (_query, signal) =>
        new Promise((_resolve, reject) =>
            signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        ),
}

describe('settleRequest', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    test.each([
        [
            'settles a stalled request empty at the deadline',
            false,
            { results: { persons: { items: [] } }, failed: true },
        ],
        ['drops a request a newer query aborted', true, null],
    ])('%s', async (_, superseded, expected) => {
        const controller = new AbortController()
        const settled = settleRequest(stalled, 'ada', controller.signal, context, 3000)

        if (superseded) {
            controller.abort()
        } else {
            jest.advanceTimersByTime(3000)
        }

        await expect(settled).resolves.toEqual(expected)
    })

    test.each([
        ['says more persons match when the API has a next page', 'https://example.com/next', true],
        ['says nothing more when the API has no next page', null, undefined],
    ])('%s', async (_, next, more) => {
        jest.mocked(personsList).mockResolvedValue({
            results: [{ uuid: 'p1', distinct_ids: ['d1'], properties: {} }],
            next,
        } as any)
        const persons = REMOTE_REQUESTS.find((request) => request.id === 'persons') as RemoteRequest

        const settled = await settleRequest(persons, 'ada', new AbortController().signal, context)

        expect(settled?.results.persons?.more).toEqual(more)
    })

    it('keeps the group types that answered when the deadline passes', async () => {
        jest.spyOn(api.groups, 'listClickhouse').mockImplementation((params, options) =>
            params.group_type_index === 0
                ? Promise.resolve({
                      columns: ['group_name'],
                      results: [[{ display_name: 'Acme', key: 'acme' }]],
                  } as any)
                : new Promise((_resolve, reject) =>
                      options?.signal?.addEventListener('abort', () => reject(options.signal?.reason))
                  )
        )
        const groups = REMOTE_REQUESTS.find((request) => request.id === 'groups')!
        const settled = settleRequest(
            groups,
            'acme',
            new AbortController().signal,
            {
                ...context,
                groupTypes: [0, 1].map((index) => ({
                    group_type: `type-${index}`,
                    group_type_index: index as GroupTypeIndex,
                })) as RemoteContext['groupTypes'],
            },
            3000
        )

        await jest.advanceTimersByTimeAsync(3000)

        const result = await settled
        expect(result?.failed).toBe(true)
        expect(result?.results.groups?.items.map((item) => item.id)).toEqual(['group-0-acme'])
    })

    describe('an is: type the file system does not hold', () => {
        const objects = REMOTE_REQUESTS.find((request) => request.id === 'objects')!
        const unified = (type: SearchableEntity, id: string, name: string): SearchResponse['results'][number] => ({
            type,
            result_id: id,
            extra_fields: { name },
            rank: null,
        })

        beforeEach(() => {
            jest.useRealTimers()
            jest.mocked(alertsList).mockResolvedValue({
                count: 1,
                results: [{ id: 'a1', name: 'Revenue drop', insight_display_name: 'Revenue' }],
            } as any)
            jest.mocked(conversationsTicketsList).mockResolvedValue({
                count: 1,
                results: [
                    {
                        id: 'ticket-uuid',
                        ticket_number: 42,
                        email_subject: 'Refund not received',
                        status: 'on_hold',
                        anonymous_traits: { name: 'Jane Doe', email: 'jane@example.com' },
                    },
                ],
            } as any)
            jest.mocked(productToursList).mockResolvedValue({
                count: 1,
                results: [{ id: 't1', name: 'Revenue tour' }],
            } as any)
            jest.mocked(personsList).mockResolvedValue({
                results: [{ uuid: 'p1', distinct_ids: ['d1'], properties: { email: 'ada@example.com' } }],
            } as any)
            jest.spyOn(api.search, 'list').mockImplementation(async ({ entities }) => ({
                results: entities?.includes('hog_flow')
                    ? [unified('hog_flow', 'w1', 'Revenue nudge')]
                    : [unified('endpoint', 'e1', 'revenue-daily')],
            }))
            jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ results: [], count: 0 } as any)
            jest.mocked(fileSystemSearchRetrieve).mockResolvedValue({
                results: [],
                type_counts: [],
                matched_all_words: true,
                matched_words: [],
                counts_capped: false,
                matched_with_typos: false,
            } as any)
        })

        test.each([
            ['type:alert revenue', '/alerts?alert_type=insights&alert_id=a1'],
            ['type:alert', '/alerts?alert_type=insights&alert_id=a1'],
            ['type:product_tour revenue', '/product_tours/t1'],
            ['type:workflows revenue', '/workflows/w1/workflow'],
            ['type:endpoints name:revenue', '/endpoints/revenue-daily'],
            ['type:ticket refund', '/support/tickets/42'],
            ['type:person acme', '/persons/p1'],
        ])('searches its own API for %s', async (query, href) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(result?.results.results?.items.map((item) => item.href)).toEqual([href])
        })

        test.each([
            ['type:alert user:me revenue', 'its API cannot apply createdBy'],
            ['type:alert path:Growth', 'its API cannot apply in'],
            ['type:alert revenue -legacy', 'its API cannot exclude words'],
            ['type:alert "-legacy"', 'a quoted exclusion is still an exclusion'],
            ["type:alert revenue '-legacy'", 'a single-quoted exclusion is still an exclusion'],
            ['type:ticket re', 'two letters would scan every ticket message'],
        ])('finds nothing for %s without a request, because %s', async (query) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(result?.results.results?.items).toEqual([])
            expect(alertsList).not.toHaveBeenCalled()
            expect(conversationsTicketsList).not.toHaveBeenCalled()
            expect(fileSystemSearchRetrieve).not.toHaveBeenCalled()
            expect(api.fileSystem.list).not.toHaveBeenCalled()
        })

        test.each([
            [
                'type:ticket name:refund',
                () =>
                    jest.mocked(conversationsTicketsList).mockResolvedValue({
                        count: 2,
                        results: [
                            { id: 't-1', ticket_number: 1, email_subject: 'Refund not received' },
                            { id: 't-2', ticket_number: 2, email_subject: 'Card declined' },
                        ],
                    } as any),
                ['/support/tickets/1'],
            ],
            [
                'type:product_tour name:"revenue tour"',
                () =>
                    jest.mocked(productToursList).mockResolvedValue({
                        count: 2,
                        results: [
                            { id: 'p1', name: 'Revenue tour' },
                            { id: 'p2', name: 'Onboarding', description: 'A revenue tour for new users' },
                        ],
                    } as any),
                ['/product_tours/p1'],
            ],
        ])('keeps only the results whose name matches for %s', async (query, mockResults, hrefs) => {
            mockResults()
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(result?.results.results?.items.map((item) => item.href)).toEqual(hrefs)
        })

        test.each([
            ['type:alert revenue', () => alertsList, ['1', { search: 'revenue', limit: 5 }, expect.anything()]],
            [
                'type:workflows',
                () => api.search.list,
                [{ q: undefined, entities: ['hog_flow'], include_counts: false }, expect.anything()],
            ],
            [
                'type:endpoints',
                () => api.search.list,
                [{ q: undefined, entities: ['endpoint'], include_counts: false }, expect.anything()],
            ],
        ])('requests %s with only the parameters it needs', async (query, endpoint, params) => {
            await settleRequest(objects, query, new AbortController().signal, context)
            expect(endpoint()).toHaveBeenCalledWith(...params)
        })

        test.each([
            ['type:ticket refund', 150],
            ['type:alert', 150],
            ['type:dashboard revenue', 50],
            ['revenue', 50],
        ])('waits for typing to pause before searching %s', (query, debounceMs) => {
            expect(requestDebounceMs(objects, query)).toBe(debounceMs)
        })

        test.each([
            ['type:ticket refund', 'refund'],
            ['type:ticket #42', '#42'],
            ['type:ticket', undefined],
        ])('sends %s to the ticket list as search %s', async (query, search) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(conversationsTicketsList).toHaveBeenCalledWith('1', { search, limit: 20 }, expect.anything())
            expect(result?.results.results?.items).toEqual([
                expect.objectContaining({
                    name: 'Refund not received',
                    productCategory: '#42 · Jane Doe · On hold',
                    href: '/support/tickets/42',
                }),
            ])
        })

        test.each([
            ['type:workflows name:venue', () => hogFlowsList, ['1', { name: 'venue', limit: 20 }, expect.anything()]],
            [
                'type:workflows name:venue nudge',
                () => api.search.list,
                [{ q: 'nudge', entities: ['hog_flow'], include_counts: false }, expect.anything()],
            ],
        ])('keeps name: apart from the full-text search for %s', async (query, endpoint, params) => {
            jest.mocked(hogFlowsList).mockResolvedValue({
                count: 1,
                results: [{ id: 'w1', name: 'Revenue nudge', created_at: '2026-01-01T00:00:00Z' }],
            } as any)
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(endpoint()).toHaveBeenCalledWith(...params)
            expect(result?.results.results?.items.map((item) => item.href)).toEqual(['/workflows/w1/workflow'])
        })

        test.each([
            ['type:ticket name:42', undefined],
            ['type:ticket name:#42', undefined],
        ])('searches subjects rather than ticket numbers for %s', async (query, search) => {
            jest.mocked(conversationsTicketsList).mockResolvedValue({
                count: 2,
                results: [
                    { id: 't-7', ticket_number: 7, email_subject: 'Refund for order #42' },
                    { id: 't-42', ticket_number: 42, email_subject: 'Card declined' },
                ],
            } as any)
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(conversationsTicketsList).toHaveBeenCalledWith('1', { search, limit: 20 }, expect.anything())
            expect(result?.results.results?.items.map((item) => item.href)).toEqual(['/support/tickets/7'])
        })

        test.each([
            [
                'the identified person before older traits',
                { properties: { name: 'Jane Smith', email: 'jane@example.com' } },
                { name: 'Jane Doe' },
                '#42 · Jane Smith · On hold',
            ],
            [
                "the person's email when traits are empty",
                { properties: { email: 'sam@example.org' } },
                {},
                '#42 · sam@example.org · On hold',
            ],
        ])('labels the ticket customer with %s', async (_, person, traits, productCategory) => {
            jest.mocked(conversationsTicketsList).mockResolvedValue({
                count: 1,
                results: [
                    {
                        id: 'ticket-uuid',
                        ticket_number: 42,
                        email_subject: 'Refund not received',
                        status: 'on_hold',
                        person,
                        anonymous_traits: traits,
                    },
                ],
            } as any)
            const result = await settleRequest(objects, 'type:ticket refund', new AbortController().signal, context)
            expect(result?.results.results?.items).toEqual([expect.objectContaining({ productCategory })])
        })
    })

    describe('an is: type that covers several file system types', () => {
        const objects = REMOTE_REQUESTS.find((request) => request.id === 'objects')!
        const entry = (type: string, id: string, created_at: string): object => ({
            id,
            path: `Unfiled/Destinations/${id}`,
            type,
            ref: id,
            created_at,
        })
        const searchesSent = (mock: jest.Mock | jest.SpyInstance, argIndex: number): string[] =>
            mock.mock.calls.map((call: any[]) => call[argIndex].search).sort()

        beforeEach(() => {
            jest.useRealTimers()
            jest.spyOn(api.fileSystem, 'list').mockImplementation(
                async ({ search }) =>
                    ({
                        count: 1,
                        results: String(search).includes('site_destination')
                            ? [entry('hog_function/site_destination', 'browser', '2026-01-02T00:00:00Z')]
                            : [entry('hog_function/destination', 'webhook', '2026-01-01T00:00:00Z')],
                    }) as any
            )
            jest.mocked(fileSystemSearchRetrieve).mockResolvedValue({
                results: [],
                type_counts: [],
                matched_all_words: true,
                matched_words: [],
                counts_capped: false,
                matched_with_typos: false,
            } as any)
        })

        test.each([
            [
                'type:hog_function/destination user:me',
                ['type:hog_function/destination user:me', 'type:hog_function/site_destination user:me'],
                [],
            ],
            [
                'type:hog_function/destination slack',
                [],
                ['type:hog_function/destination slack', 'type:hog_function/site_destination slack'],
            ],
            [
                '-type:hog_function/destination slack',
                [],
                ['-type:hog_function/destination -type:hog_function/site_destination slack'],
            ],
        ])('searches every type the scope covers for %s', async (query, listSearches, rankedSearches) => {
            await settleRequest(objects, query, new AbortController().signal, context)
            expect(searchesSent(jest.mocked(api.fileSystem.list), 0)).toEqual(listSearches)
            expect(searchesSent(jest.mocked(fileSystemSearchRetrieve), 1)).toEqual(rankedSearches)
        })

        it('asks each type for its newest entries before merging them', async () => {
            await settleRequest(objects, 'type:hog_function/destination', new AbortController().signal, context)
            expect(jest.mocked(api.fileSystem.list).mock.calls.map(([params]) => params.orderBy)).toEqual([
                '-created_at',
                '-created_at',
            ])
        })

        it('merges the types newest first', async () => {
            const result = await settleRequest(
                objects,
                'type:hog_function/destination',
                new AbortController().signal,
                context
            )
            expect(result?.results.results?.items.map((item) => item.record?.type)).toEqual([
                'hog_function/site_destination',
                'hog_function/destination',
            ])
        })
    })
})

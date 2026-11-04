import api from 'lib/api'

import { fileSystemSearchRetrieve } from '~/generated/core/api'
import { GroupTypeIndex, SearchResponse, SearchableEntity } from '~/types'

import { alertsList } from 'products/alerts/frontend/generated/api'
import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'
import { productToursList } from 'products/product_tours/frontend/generated/api'

import { REMOTE_REQUESTS, RemoteContext, RemoteRequest, settleRequest } from './commandKSources'

jest.mock('products/alerts/frontend/generated/api', () => ({ alertsList: jest.fn() }))
jest.mock('products/conversations/frontend/generated/api', () => ({ conversationsTicketsList: jest.fn() }))
jest.mock('products/product_tours/frontend/generated/api', () => ({ productToursList: jest.fn() }))
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
        ['settles a stalled request empty at the deadline', false, { results: { persons: [] }, failed: true }],
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
        expect(result?.results.groups?.map((item) => item.id)).toEqual(['group-0-acme'])
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
        ])('searches its own API for %s', async (query, href) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(result?.results.results?.map((item) => item.href)).toEqual([href])
        })

        test.each([
            ['type:alert user:me revenue', 'its API cannot apply createdBy'],
            ['type:alert path:Growth', 'its API cannot apply in'],
            ['type:alert revenue -legacy', 'its API cannot exclude words'],
            ['type:ticket re', 'two letters would scan every ticket message'],
        ])('finds nothing for %s without a request, because %s', async (query) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(result?.results.results).toEqual([])
            expect(alertsList).not.toHaveBeenCalled()
            expect(conversationsTicketsList).not.toHaveBeenCalled()
            expect(fileSystemSearchRetrieve).not.toHaveBeenCalled()
            expect(api.fileSystem.list).not.toHaveBeenCalled()
        })

        test.each([
            ['type:ticket refund', 'refund'],
            ['type:ticket #42', '#42'],
            ['type:ticket', undefined],
        ])('sends %s to the ticket list as search %s', async (query, search) => {
            const result = await settleRequest(objects, query, new AbortController().signal, context)
            expect(conversationsTicketsList).toHaveBeenCalledWith('1', { search, limit: 20 }, expect.anything())
            expect(result?.results.results).toEqual([
                expect.objectContaining({
                    name: 'Refund not received',
                    productCategory: '#42 · Jane Doe · On hold',
                    href: '/support/tickets/42',
                }),
            ])
        })
    })
})

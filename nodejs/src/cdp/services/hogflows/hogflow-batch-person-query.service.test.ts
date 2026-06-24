import { Team } from '~/types'

import {
    BlastRadiusPersonsResponse,
    BlastRadiusResponse,
    HogFlowBatchPersonQueryService,
} from './hogflow-batch-person-query.service'

type MockedInternalFetchResult = {
    fetchResponse: { status: number; text: () => Promise<string> } | null
    fetchError: Error | null
}

const createFetchResponse = (status: number, body: unknown): { status: number; text: () => Promise<string> } => {
    const responseBody = typeof body === 'string' ? body : JSON.stringify(body)
    return {
        status,
        text: jest.fn().mockResolvedValue(responseBody),
    }
}

const FETCH_TIMEOUT_MS = 30_000

describe('HogFlowBatchPersonQueryService', () => {
    const team = { id: 123 } as Team
    const filters = { properties: [], filter_test_accounts: true }

    let fetchMock: jest.Mock<Promise<MockedInternalFetchResult>, []>

    beforeEach(() => {
        fetchMock = jest.fn()
    })

    // retryBackoffMs: 0 keeps tests fast — the retry mechanics are what we care about,
    // not the wall-clock backoff.
    const createService = (): HogFlowBatchPersonQueryService => {
        return new HogFlowBatchPersonQueryService({ fetch: fetchMock } as any, { retryBackoffMs: 0 })
    }

    describe('getBlastRadius', () => {
        it('calls the Django endpoint and returns parsed response', async () => {
            const service = createService()
            const response: BlastRadiusResponse = { users_affected: 12, total_users: 50 }

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, response),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters, 1)).resolves.toEqual(response)

            expect(fetchMock).toHaveBeenCalledTimes(1)
            expect(fetchMock).toHaveBeenCalledWith({
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius',
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({
                        filters,
                        group_type_index: 1,
                    }),
                    timeoutMs: FETCH_TIMEOUT_MS,
                },
            })
        })

        it('sends the same request when INTERNAL_API_SECRET is not configured', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, { users_affected: 1, total_users: 2 }),
                fetchError: null,
            })

            await service.getBlastRadius(team, filters)

            expect(fetchMock).toHaveBeenCalledWith({
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius',
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                    }),
                    timeoutMs: FETCH_TIMEOUT_MS,
                },
            })
        })

        it('retries once on 5xx and throws when both attempts fail', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(500, 'server exploded'),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow(
                'HTTP 500 from /api/projects/123/internal/hog_flows/user_blast_radius: server exploded'
            )
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        it('does NOT retry on 4xx — client errors are non-retryable', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(403, 'forbidden'),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow(
                'HTTP 403 from /api/projects/123/internal/hog_flows/user_blast_radius: forbidden'
            )
            expect(fetchMock).toHaveBeenCalledTimes(1)
        })

        it('retries once on fetchError and throws when both attempts fail', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('The operation was aborted due to timeout'),
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow(
                'The operation was aborted due to timeout'
            )
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        it('retries once on fetchError and returns the response on second attempt', async () => {
            const service = createService()
            const response: BlastRadiusResponse = { users_affected: 7, total_users: 100 }

            fetchMock
                .mockResolvedValueOnce({
                    fetchResponse: null,
                    fetchError: new Error('The operation was aborted due to timeout'),
                })
                .mockResolvedValueOnce({
                    fetchResponse: createFetchResponse(200, response),
                    fetchError: null,
                })

            await expect(service.getBlastRadius(team, filters)).resolves.toEqual(response)
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })
    })

    describe('getBlastRadiusPersons', () => {
        it("uses the first page's cursor for the next page request", async () => {
            const service = createService()
            const firstPageResponse: BlastRadiusPersonsResponse = {
                users_affected: ['person_1'],
                cursor: 'next-cursor',
                has_more: true,
            }
            const secondPageResponse: BlastRadiusPersonsResponse = {
                users_affected: ['person_2'],
                cursor: null,
                has_more: false,
            }

            fetchMock.mockResolvedValueOnce({
                fetchResponse: createFetchResponse(200, firstPageResponse),
                fetchError: null,
            })
            fetchMock.mockResolvedValueOnce({
                fetchResponse: createFetchResponse(200, secondPageResponse),
                fetchError: null,
            })

            const firstPage = await service.getBlastRadiusPersons(team, filters, 2)
            await expect(service.getBlastRadiusPersons(team, filters, 2, firstPage.cursor)).resolves.toEqual(
                secondPageResponse
            )

            expect(fetchMock).toHaveBeenCalledTimes(2)
            expect(fetchMock).toHaveBeenNthCalledWith(1, {
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: null,
                    }),
                    timeoutMs: FETCH_TIMEOUT_MS,
                },
            })
            expect(fetchMock).toHaveBeenNthCalledWith(2, {
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: 'next-cursor',
                    }),
                    timeoutMs: FETCH_TIMEOUT_MS,
                },
            })
        })

        it('sends cursor as null when not provided', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, {
                    users_affected: [],
                    cursor: null,
                    has_more: false,
                }),
                fetchError: null,
            })

            await service.getBlastRadiusPersons(team, filters)

            expect(fetchMock).toHaveBeenCalledWith({
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                        cursor: null,
                    }),
                    timeoutMs: FETCH_TIMEOUT_MS,
                },
            })
        })

        it('does NOT retry on 4xx — client errors are non-retryable', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(403, 'forbidden'),
                fetchError: null,
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow(
                'HTTP 403 from /api/projects/123/internal/hog_flows/user_blast_radius_persons: forbidden'
            )
            expect(fetchMock).toHaveBeenCalledTimes(1)
        })

        it('retries once on fetchError (e.g. AbortSignal timeout) before failing', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('The operation was aborted due to timeout'),
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow(
                'The operation was aborted due to timeout'
            )
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        it('returns successful response when first attempt times out and retry succeeds', async () => {
            const service = createService()
            const response: BlastRadiusPersonsResponse = {
                users_affected: ['person_a', 'person_b'],
                cursor: 'cursor-1',
                has_more: false,
            }

            fetchMock
                .mockResolvedValueOnce({
                    fetchResponse: null,
                    fetchError: new Error('The operation was aborted due to timeout'),
                })
                .mockResolvedValueOnce({
                    fetchResponse: createFetchResponse(200, response),
                    fetchError: null,
                })

            await expect(service.getBlastRadiusPersons(team, filters)).resolves.toEqual(response)
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })
    })
})

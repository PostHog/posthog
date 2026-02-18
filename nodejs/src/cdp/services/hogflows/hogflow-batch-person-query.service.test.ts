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

describe('HogFlowBatchPersonQueryService', () => {
    const team = { id: 123 } as Team
    const filters = { properties: [], filter_test_accounts: true }

    let fetchMock: jest.Mock<Promise<MockedInternalFetchResult>, []>

    beforeEach(() => {
        fetchMock = jest.fn()
    })

    const createService = (internalApiSecret?: string): HogFlowBatchPersonQueryService => {
        return new HogFlowBatchPersonQueryService({
            SITE_URL: 'http://localhost:8000',
            INTERNAL_API_SECRET: internalApiSecret,
            internalFetchService: {
                fetch: fetchMock,
            },
        } as any)
    }

    describe('getBlastRadius', () => {
        it('calls the Django endpoint with internal auth header and returns parsed response', async () => {
            const service = createService('internal-secret')
            const response: BlastRadiusResponse = { users_affected: 12, total_users: 50 }

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, response),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters, 1)).resolves.toEqual(response)

            expect(fetchMock).toHaveBeenCalledTimes(1)
            expect(fetchMock).toHaveBeenCalledWith({
                url: 'http://localhost:8000/api/projects/123/internal/hog_flows/user_blast_radius',
                fetchParams: {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer internal-secret',
                    },
                    body: JSON.stringify({
                        filters,
                        group_type_index: 1,
                    }),
                },
            })
        })

        it('omits Authorization header when INTERNAL_API_SECRET is not configured', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, { users_affected: 1, total_users: 2 }),
                fetchError: null,
            })

            await service.getBlastRadius(team, filters)

            expect(fetchMock).toHaveBeenCalledWith({
                url: 'http://localhost:8000/api/projects/123/internal/hog_flows/user_blast_radius',
                fetchParams: {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                    }),
                },
            })
        })

        it('throws when Django responds with non-200 status', async () => {
            const service = createService('internal-secret')

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(500, 'server exploded'),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow(
                'Failed to fetch blast radius: 500 server exploded'
            )
        })

        it('throws fetchError when internal fetch fails', async () => {
            const service = createService('internal-secret')

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('network down'),
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow('network down')
        })
    })

    describe('getBlastRadiusPersons', () => {
        it("uses the first page's cursor for the next page request", async () => {
            const service = createService('internal-secret')
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
                url: 'http://localhost:8000/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer internal-secret',
                    },
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: null,
                    }),
                },
            })
            expect(fetchMock).toHaveBeenNthCalledWith(2, {
                url: 'http://localhost:8000/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer internal-secret',
                    },
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: 'next-cursor',
                    }),
                },
            })
        })

        it('sends cursor as null when not provided', async () => {
            const service = createService('internal-secret')

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
                url: 'http://localhost:8000/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer internal-secret',
                    },
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                        cursor: null,
                    }),
                },
            })
        })

        it('throws when persons endpoint responds with non-200 status', async () => {
            const service = createService('internal-secret')

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(403, 'forbidden'),
                fetchError: null,
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow(
                'Failed to fetch blast radius persons: 403 forbidden'
            )
        })

        it('throws fetchError when persons fetch fails', async () => {
            const service = createService('internal-secret')

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('timeout'),
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow('timeout')
        })
    })
})

import { register } from 'prom-client'

import { Team } from '~/types'

import {
    AccountAudienceResponse,
    AudienceFetchTimeoutError,
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

const AUDIENCE_FETCH_TIMEOUT_MS = 30_000

describe('HogFlowBatchPersonQueryService', () => {
    const team = { id: 123 } as Team
    const filters = { properties: [], filter_test_accounts: true }

    let fetchMock: jest.Mock<Promise<MockedInternalFetchResult>, []>

    beforeEach(() => {
        fetchMock = jest.fn()
    })

    const createService = (): HogFlowBatchPersonQueryService => {
        return new HogFlowBatchPersonQueryService({ fetch: fetchMock } as any, AUDIENCE_FETCH_TIMEOUT_MS)
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
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters,
                        group_type_index: 1,
                    }),
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
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                    }),
                },
            })
        })

        it('throws when Django responds with non-200 status', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(500, 'server exploded'),
                fetchError: null,
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow(
                'Failed to fetch blast radius: 500 server exploded'
            )
        })

        it('throws fetchError when internal fetch fails', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('network down'),
            })

            await expect(service.getBlastRadius(team, filters)).rejects.toThrow('network down')
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
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: null,
                        dedupe_key: null,
                    }),
                },
            })
            expect(fetchMock).toHaveBeenNthCalledWith(2, {
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters,
                        group_type_index: 2,
                        cursor: 'next-cursor',
                        dedupe_key: null,
                    }),
                },
            })
        })

        it.each([
            ['email dedupe key is forwarded', 'email' as const, 'email'],
            ['missing dedupe key is sent as null', undefined, null],
        ])('%s', async (_name, dedupeKey, expectedBodyValue) => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, {
                    users_affected: [],
                    cursor: null,
                    has_more: false,
                }),
                fetchError: null,
            })

            await service.getBlastRadiusPersons(team, filters, undefined, null, dedupeKey)

            expect(fetchMock).toHaveBeenCalledWith({
                urlPath: '/api/projects/123/internal/hog_flows/user_blast_radius_persons',
                fetchParams: {
                    method: 'POST',
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters,
                        group_type_index: undefined,
                        cursor: null,
                        dedupe_key: expectedBodyValue,
                    }),
                },
            })
        })

        it('throws when persons endpoint responds with non-200 status', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(403, 'forbidden'),
                fetchError: null,
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow(
                'Failed to fetch blast radius persons: 403 forbidden'
            )
        })

        it('throws fetchError when persons fetch fails', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('timeout'),
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow('timeout')
        })
    })

    describe('getAccountAudiencePage', () => {
        const accountFilters = { audience_type: 'accounts', properties: [], tag_names: ['vip'] }

        it('calls the Django endpoint and returns parsed response', async () => {
            const service = createService()
            const response: AccountAudienceResponse = {
                accounts: ['acme', 'globex'],
                cursor: 'globex',
                has_more: false,
                group_type: 'customer',
            }

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(200, response),
                fetchError: null,
            })

            await expect(service.getAccountAudiencePage(team, accountFilters, 'abc')).resolves.toEqual(response)

            expect(fetchMock).toHaveBeenCalledWith({
                urlPath: '/api/projects/123/internal/hog_flows/account_audience',
                fetchParams: {
                    method: 'POST',
                    timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS,
                    body: JSON.stringify({
                        filters: accountFilters,
                        cursor: 'abc',
                    }),
                },
            })
        })

        it('throws when the endpoint responds with non-200 status', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({
                fetchResponse: createFetchResponse(400, 'bad filters'),
                fetchError: null,
            })

            await expect(service.getAccountAudiencePage(team, accountFilters)).rejects.toThrow(
                'Failed to fetch account audience: 400 bad filters'
            )
        })
    })
    describe('audience fetch timeouts', () => {
        const timeoutError = (): Error => {
            const error = new Error('The operation was aborted due to timeout')
            error.name = 'TimeoutError'
            return error
        }

        const timeoutCount = async (endpoint: string): Promise<number> => {
            const metric = await register.getSingleMetric('cdp_batch_hog_flow_audience_fetch_timeout')?.get()
            return metric?.values.find((value) => value.labels.endpoint === endpoint)?.value ?? 0
        }

        it.each([
            ['user_blast_radius', (service: HogFlowBatchPersonQueryService) => service.getBlastRadius(team, filters)],
            [
                'user_blast_radius_persons',
                (service: HogFlowBatchPersonQueryService) => service.getBlastRadiusPersons(team, filters),
            ],
            [
                'account_audience',
                (service: HogFlowBatchPersonQueryService) => service.getAccountAudiencePage(team, {}),
            ],
        ])('reports a %s timeout as AudienceFetchTimeoutError and counts it', async (endpoint, call) => {
            const service = createService()
            const before = await timeoutCount(endpoint)

            fetchMock.mockResolvedValue({ fetchResponse: null, fetchError: timeoutError() })

            const error = await call(service).catch((err: unknown) => err)

            expect(error).toBeInstanceOf(AudienceFetchTimeoutError)
            expect(error).toMatchObject({ endpoint, timeoutMs: AUDIENCE_FETCH_TIMEOUT_MS })
            expect((error as Error).message).toBe(
                `Audience fetch to ${endpoint} timed out after 30000ms. The audience query did not finish inside ` +
                    `CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS.`
            )
            expect(await timeoutCount(endpoint)).toBe(before + 1)
        })

        it('reports an abort wrapped in cause as a timeout', async () => {
            const service = createService()
            const aborted = new Error('aborted')
            aborted.name = 'AbortError'

            fetchMock.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('fetch failed', { cause: aborted }),
            })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toBeInstanceOf(AudienceFetchTimeoutError)
        })

        it('keeps a transport error that is not a timeout unchanged', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({ fetchResponse: null, fetchError: new Error('network down') })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.not.toBeInstanceOf(
                AudienceFetchTimeoutError
            )
        })

        it('names the endpoint when the fetch returns no response and no error', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({ fetchResponse: null, fetchError: null })

            await expect(service.getBlastRadiusPersons(team, filters)).rejects.toThrow(
                'Audience fetch to user_blast_radius_persons returned no response'
            )
        })
    })
})

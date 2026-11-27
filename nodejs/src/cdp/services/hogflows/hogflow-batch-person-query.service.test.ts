import { register } from 'prom-client'

import { Team } from '~/types'

import {
    AccountAudienceResponse,
    AudienceFetchTimeoutError,
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
                'audience_snapshot_page',
                (service: HogFlowBatchPersonQueryService) => service.getAudienceSnapshotPage(team, 'batch-1'),
            ],
            ['account_audience', (service: HogFlowBatchPersonQueryService) => service.getAccountAudiencePage(team, {})],
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

            await expect(service.getAudienceSnapshotPage(team, 'batch-1')).rejects.toBeInstanceOf(
                AudienceFetchTimeoutError
            )
        })

        it('keeps a transport error that is not a timeout unchanged', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({ fetchResponse: null, fetchError: new Error('network down') })

            await expect(service.getAudienceSnapshotPage(team, 'batch-1')).rejects.not.toBeInstanceOf(
                AudienceFetchTimeoutError
            )
        })

        it('names the endpoint when the fetch returns no response and no error', async () => {
            const service = createService()

            fetchMock.mockResolvedValue({ fetchResponse: null, fetchError: null })

            await expect(service.getAudienceSnapshotPage(team, 'batch-1')).rejects.toThrow(
                'Audience fetch to audience_snapshot_page returned no response'
            )
        })
    })

    describe('audience fetch duration', () => {
        const fetchCount = async (endpoint: string, outcome: string): Promise<number> => {
            const metric = await register.getSingleMetric('cdp_batch_hog_flow_audience_fetch_duration_seconds')?.get()
            const values = (metric?.values ?? []) as Array<{
                metricName?: string
                value: number
                labels: { endpoint?: string; outcome?: string }
            }>
            return (
                values.find(
                    (value) =>
                        value.metricName === 'cdp_batch_hog_flow_audience_fetch_duration_seconds_count' &&
                        value.labels.endpoint === endpoint &&
                        value.labels.outcome === outcome
                )?.value ?? 0
            )
        }

        // The alert reads the outcome label; a fetch filed under the wrong one keeps it silent.
        it.each([
            [
                'a 200 response',
                'success',
                {
                    fetchResponse: createFetchResponse(200, { users_affected: [], cursor: null, has_more: false }),
                    fetchError: null,
                },
            ],
            ['a 500 response', 'error', { fetchResponse: createFetchResponse(500, 'boom'), fetchError: null }],
            ['a transport error', 'error', { fetchResponse: null, fetchError: new Error('network down') }],
            [
                'a client timeout',
                'timeout',
                { fetchResponse: null, fetchError: Object.assign(new Error('aborted'), { name: 'TimeoutError' }) },
            ],
        ])('records %s under outcome %s', async (_name, outcome, result) => {
            const service = createService()
            const before = await fetchCount('audience_snapshot_page', outcome)

            fetchMock.mockResolvedValue(result as MockedInternalFetchResult)
            await service.getAudienceSnapshotPage(team, 'batch-1').catch(() => undefined)

            expect(await fetchCount('audience_snapshot_page', outcome)).toBe(before + 1)
        })
    })
})

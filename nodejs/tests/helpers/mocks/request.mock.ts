import { FetchResponse } from '~/common/utils/request'

jest.mock('~/common/utils/request', () => {
    return {
        // The SSRF-safe DNS lookup does no HTTP I/O and is needed by the SMTP transport
        // pool even when fetch is mocked — pass the real implementation through.
        httpStaticLookup: jest.requireActual('~/common/utils/request').httpStaticLookup,
        fetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                headers: {},
                json: () => Promise.resolve({ success: true }),
                text: () => Promise.resolve(JSON.stringify({ success: true })),
            } as FetchResponse)
        ),
        internalFetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(''),
            } as FetchResponse)
        ),
    }
})

export const mockFetch: jest.Mock<Promise<FetchResponse>> = require('~/common/utils/request').fetch
export const mockInternalFetch: jest.Mock<Promise<FetchResponse>> = require('~/common/utils/request').internalFetch

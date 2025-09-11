import { FetchResponse } from '../../../src/utils/request'

jest.mock('../../../src/utils/request', () => {
    return {
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

export const mockFetch: jest.Mock<Promise<FetchResponse>> = require('../../../src/utils/request').fetch
export const mockInternalFetch: jest.Mock<Promise<FetchResponse>> = require('../../../src/utils/request').internalFetch

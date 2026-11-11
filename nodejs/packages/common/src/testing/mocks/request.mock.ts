import { FetchResponse } from '~/utils/request'

// Relative, not aliased: consumers load the compiled helper, and tsc-alias leaves jest.mock specifiers alone.
jest.mock('../../utils/request', () => {
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
        closeSharedAgents: jest.fn(() => Promise.resolve()),
    }
})

export const mockFetch: jest.Mock<Promise<FetchResponse>> = require('~/utils/request').fetch
export const mockInternalFetch: jest.Mock<Promise<FetchResponse>> = require('~/utils/request').internalFetch

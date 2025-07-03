const { readFileSync } = require('fs')
const { DateTime } = require('luxon')
const { join } = require('path')

import fetch from 'node-fetch'

import { logger, shutdownLogger } from './src/utils/logger'

// Setup spies on the logger for all tests to use

jest.mock('node-fetch', () => ({
    __esModule: true,
    ...jest.requireActual('node-fetch'), // Only mock fetch(), leave Request, Response, FetchError, etc. alone
    default: jest.fn(),
}))

jest.mock('undici', () => ({
    __esModule: true,
    ...jest.requireActual('undici'), // Only mock fetch(), leave Request, Response, FetchError, etc. alone
    fetch: jest.spyOn(jest.requireActual('undici'), 'fetch'),
}))

beforeEach(() => {
    jest.spyOn(logger, 'info')
    jest.spyOn(logger, 'warn')
    jest.spyOn(logger, 'debug')
    jest.spyOn(logger, 'error')

    jest.mocked(logger.info).mockClear()
    jest.mocked(logger.warn).mockClear()
    jest.mocked(logger.debug).mockClear()
    jest.mocked(logger.error).mockClear()

    const responsesToUrls = {
        'https://google.com/results.json?query=fetched': { count: 2, query: 'bla', results: [true, true] },
        'https://mmdbcdn.posthog.net/': readFileSync(join(__dirname, 'tests', 'assets', 'GeoLite2-City-Test.mmdb.br')),
        'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2': { hello: 'world' },
        'https://onevent.com/': { success: true },
        'https://www.example.com': { example: 'data' },
    }

    const headersToUrls = {
        'https://mmdbcdn.posthog.net/': new Map([
            ['content-type', 'vnd.maxmind.maxmind-db'],
            ['content-disposition', `attachment; filename="GeoLite2-City-${DateTime.local().toISODate()}.mmdb"`],
        ]),
    }

    // Create a proper Response-like object factory
    const createMockResponse = (url, options = {}) => {
        const responseBody = responsesToUrls[url] || { fetch: 'mock' }
        const responseHeaders = headersToUrls[url] || new Map()
        const responseText =
            typeof responseBody === 'object' && !Buffer.isBuffer(responseBody)
                ? JSON.stringify(responseBody)
                : String(responseBody)

        // Create a proper Response-like object that matches the interface expected by recordedFetch
        return {
            // Properties
            status: options.method === 'PUT' ? 201 : 200,
            statusText: 'OK',
            ok: true,
            headers: {
                get: (name) => {
                    if (responseHeaders instanceof Map) {
                        return responseHeaders.get(name) || null
                    }
                    return null
                },
                forEach: (callback) => {
                    if (responseHeaders instanceof Map) {
                        responseHeaders.forEach((value, key) => callback(value, key))
                    }
                },
            },

            // Methods
            buffer: () => Promise.resolve(Buffer.isBuffer(responseBody) ? responseBody : Buffer.from(responseText)),
            json: () => Promise.resolve(responseBody),
            text: () => Promise.resolve(responseText),

            // Clone method that returns a similar object with the same interface
            clone: function () {
                return createMockResponse(url, options)
            },
        }
    }

    jest.mocked(fetch).mockImplementation((url, options = {}) => {
        return Promise.resolve(createMockResponse(url, options))
    })
})

beforeAll(() => {
    // We use procese.exit in a few places, which end up terminating tests
    // if we don't mock it.
    jest.spyOn(process, 'exit').mockImplementation((number) => {
        throw new Error('process.exit: ' + number)
    })
})

afterAll(async () => {
    // Shutdown logger to prevent Jest from hanging on open handles
    await shutdownLogger()
})

const { readFileSync } = require('fs')
const { DateTime } = require('luxon')
const { join } = require('path')

import fetch from 'node-fetch'

import { status } from './src/utils/status'

jest.mock('node-fetch', () => ({
    __esModule: true,
    ...jest.requireActual('node-fetch'), // Only mock fetch(), leave Request, Response, FetchError, etc. alone
    default: jest.fn(),
}))

beforeEach(() => {
    const responsesToUrls = {
        'https://google.com/results.json?query=fetched': { count: 2, query: 'bla', results: [true, true] },
        'https://mmdbcdn.posthog.net/': readFileSync(join(__dirname, 'tests', 'assets', 'GeoLite2-City-Test.mmdb.br')),
        'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2': { hello: 'world' },
    }
    const headersToUrls = {
        'https://mmdbcdn.posthog.net/': new Map([
            ['content-type', 'vnd.maxmind.maxmind-db'],
            ['content-disposition', `attachment; filename="GeoLite2-City-${DateTime.local().toISODate()}.mmdb"`],
        ]),
    }

    jest.mocked(fetch).mockImplementation(
        (url, options) =>
            new Promise((resolve) =>
                resolve({
                    buffer: () => new Promise((resolve) => resolve(responsesToUrls[url]) || Buffer.from('fetchmock')),
                    json: () => new Promise((resolve) => resolve(responsesToUrls[url]) || { fetch: 'mock' }),
                    text: () => new Promise((resolve) => resolve(JSON.stringify(responsesToUrls[url])) || 'fetchmock'),
                    status: () => (options.method === 'PUT' ? 201 : 200),
                    headers: headersToUrls[url],
                })
            )
    )
})

// NOTE: in testing we use the pino-pretty transport, which results in a handle
// that we need to close to allow Jest to exit properly.
afterAll(() => status.close())

beforeAll(() => {
    // We use procese.exit in a few places, which end up terminating tests
    // if we don't mock it.
    jest.spyOn(process, 'exit').mockImplementation((number) => {
        throw new Error('process.exit: ' + number)
    })
})

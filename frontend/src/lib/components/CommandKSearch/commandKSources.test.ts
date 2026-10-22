import { RemoteContext, RemoteRequest, settleRequest } from './commandKSources'

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
})

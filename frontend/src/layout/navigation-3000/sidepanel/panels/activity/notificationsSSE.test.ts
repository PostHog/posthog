import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { InAppNotification } from '~/types'

import { SSEDisconnectedError, connectToNotificationsSSE, shouldRetrySSE } from './notificationsSSE'

jest.mock('lib/api')

const mockStream = api.stream as jest.MockedFunction<typeof api.stream>

function makeNotification(overrides: Partial<InAppNotification> = {}): InAppNotification {
    return {
        id: 'test-id',
        team_id: 1,
        notification_type: 'comment_mention',
        priority: 'normal',
        title: 'Test',
        body: '',
        read: false,
        read_at: null,
        resource_type: null,
        resource_id: '',
        target_type: 'user',
        target_id: '1',
        source_url: '',
        source_type: null,
        source_id: null,
        metadata: null,
        created_at: '2026-04-01T00:00:00Z',
        ...overrides,
    }
}

describe('connectToNotificationsSSE', () => {
    const url = 'https://live.us.posthog.com/notifications'
    const token = 'test-token'
    let abortController: AbortController

    beforeEach(() => {
        abortController = new AbortController()
        mockStream.mockReset()
    })

    it('calls api.stream with correct URL and auth header', async () => {
        mockStream.mockResolvedValue()
        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn())

        expect(mockStream).toHaveBeenCalledWith(
            url,
            expect.objectContaining({
                headers: { Authorization: `Bearer ${token}` },
                signal: abortController.signal,
            })
        )
    })

    it('parses SSE messages and calls onNotification', async () => {
        const onNotification = jest.fn()
        const notification = makeNotification()

        mockStream.mockImplementation(async (_url, opts) => {
            opts.onMessage({ data: JSON.stringify(notification) } as any)
        })

        await connectToNotificationsSSE(url, token, abortController.signal, onNotification)
        expect(onNotification).toHaveBeenCalledWith(notification)
    })

    it('ignores malformed messages', async () => {
        const onNotification = jest.fn()

        mockStream.mockImplementation(async (_url, opts) => {
            opts.onMessage({ data: 'not-json' } as any)
        })

        await connectToNotificationsSSE(url, token, abortController.signal, onNotification)
        expect(onNotification).not.toHaveBeenCalled()
    })

    it('throws from onError to stop fetchEventSource retries', async () => {
        mockStream.mockImplementation(async (_url, opts) => {
            expect(() => opts.onError(new Error('connection lost'))).toThrow('SSE disconnected')
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn())
    })

    it('reports a disconnect once even though fetch-event-source re-reports our own throw', async () => {
        const onError = jest.fn()

        mockStream.mockImplementation(async (_url, opts) => {
            // A non-ok status arrives via onError from inside onopen; the resulting throw then
            // lands in fetch-event-source's catch, which calls onError with it a second time.
            let rethrown: unknown
            try {
                opts.onError(new ApiError('unauthorized', 401))
            } catch (e) {
                rethrown = e
            }
            expect(() => opts.onError(rethrown)).toThrow(SSEDisconnectedError)
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn(), { onError })

        expect(onError).toHaveBeenCalledTimes(1)
        expect(onError.mock.calls[0][1]).toEqual({ reason: 'auth', streamWasLive: false })
    })

    it.each([
        ['auth failures', new SSEDisconnectedError('auth', false), false],
        ['dropped streams', new SSEDisconnectedError('stream_dropped', true), true],
    ])('shouldRetrySSE gates retries for %s', (_name, error, expected) => {
        expect(shouldRetrySSE(error)).toBe(expected)
    })

    // Last in the file on purpose: the unload flag is module-level and deliberately one-way, so any
    // case declared after this one would classify against an already-unloading page.
    it('treats a disconnect during page unload as a clean shutdown, without reporting it', async () => {
        window.dispatchEvent(new Event('beforeunload'))

        const onError = jest.fn()
        mockStream.mockImplementation(async (_url, opts) => {
            expect(() => opts.onError(new TypeError('Failed to fetch'))).toThrow(
                expect.objectContaining({ name: 'AbortError' })
            )
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn(), { onError })
        expect(onError).not.toHaveBeenCalled()
    })
})

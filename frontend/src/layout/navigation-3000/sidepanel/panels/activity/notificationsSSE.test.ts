import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { InAppNotification } from '~/types'

import { connectToNotificationsSSE } from './notificationsSSE'

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

    it('rethrows the original error from onError so the cause stays readable', async () => {
        const onError = jest.fn()
        const cause = new ApiError('Unauthorized', 401)

        mockStream.mockImplementation(async (_url, opts) => {
            expect(() => opts.onError(cause)).toThrow(cause)
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn(), { onError })
        expect(onError).toHaveBeenCalledWith(cause)
    })

    it('wraps an AbortError that did not come from our signal so the retry loop keeps retrying', async () => {
        mockStream.mockImplementation(async (_url, opts) => {
            expect(() => opts.onError(new DOMException('Aborted', 'AbortError'))).toThrow('SSE disconnected')
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn())
    })
})

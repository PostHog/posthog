import api from 'lib/api'

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

    it.each([
        ['livestream bearer token', token, { Authorization: `Bearer ${token}` }],
        ['django session cookie', undefined, undefined],
    ])('calls api.stream with correct URL and auth header (%s)', async (_name, streamToken, expectedHeaders) => {
        mockStream.mockResolvedValue()
        await connectToNotificationsSSE(url, streamToken, abortController.signal, jest.fn())

        expect(mockStream).toHaveBeenCalledWith(
            url,
            expect.objectContaining({
                headers: expectedHeaders,
                signal: abortController.signal,
            })
        )
    })

    it('reports the end event instead of treating it as a notification', async () => {
        const onNotification = jest.fn()
        const onEnd = jest.fn()
        const onFirstMessage = jest.fn()

        mockStream.mockImplementation(async (_url, opts) => {
            opts.onMessage({ event: 'end', data: 'reconnect' } as any)
        })

        await connectToNotificationsSSE(url, undefined, abortController.signal, onNotification, {
            onEnd,
            onFirstMessage,
        })
        expect(onEnd).toHaveBeenCalledTimes(1)
        expect(onNotification).not.toHaveBeenCalled()
        expect(onFirstMessage).not.toHaveBeenCalled()
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
})

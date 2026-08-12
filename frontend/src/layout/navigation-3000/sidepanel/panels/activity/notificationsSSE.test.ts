import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { InAppNotification } from '~/types'

import { connectToNotificationsSSE, isSSEAuthError, SSEDisconnectedError } from './notificationsSSE'

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

    it('surfaces a 401 as an auth error so the caller can re-mint the token', async () => {
        let thrown: unknown
        mockStream.mockImplementation(async (_url, opts) => {
            try {
                opts.onError(new ApiError('unauthorized', 401))
            } catch (e) {
                thrown = e
            }
        })

        await connectToNotificationsSSE(url, token, abortController.signal, jest.fn())

        expect(thrown).toBeInstanceOf(SSEDisconnectedError)
        expect(isSSEAuthError(thrown)).toBe(true)
    })

    it.each([
        [401, true],
        [403, true],
        [500, false],
        [undefined, false],
    ])('isSSEAuthError treats status %s as auth=%s', (status, expected) => {
        expect(isSSEAuthError(new SSEDisconnectedError(status as number | undefined))).toBe(expected)
    })
})

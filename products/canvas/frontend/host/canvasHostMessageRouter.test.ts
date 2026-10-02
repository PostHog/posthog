import {
    DATA_REQUEST_TIMEOUT_MS,
    EXTERNAL_OPEN_MIN_INTERVAL_MS,
    MAX_DATA_REQUEST_BYTES,
    createCanvasHostMessageRouter,
} from './canvasHostMessageRouter'
import { CanvasToHostMessage, HostToCanvasMessage, canvasToHostMessageSchema } from './canvasProtocol'

function setup(options: { activated?: boolean; onDataRequest?: () => Promise<unknown> } = {}): {
    route: (message: CanvasToHostMessage) => Promise<void>
    posted: HostToCanvasMessage[]
    onDataRequest: jest.Mock
    onNavigate: jest.Mock
    onCommentActivate: jest.Mock
    openExternal: jest.Mock
    onExternalOpenBlocked: jest.Mock
    clock: { now: number }
} {
    const posted: HostToCanvasMessage[] = []
    const onDataRequest = jest.fn(options.onDataRequest ?? (async () => ({ ok: true })))
    const onNavigate = jest.fn()
    const onCommentActivate = jest.fn()
    const openExternal = jest.fn()
    const onExternalOpenBlocked = jest.fn()
    const clock = { now: 10_000 }
    const route = createCanvasHostMessageRouter({
        post: (message) => posted.push(message),
        callbacks: () => ({ onDataRequest, onNavigate, onCommentActivate }),
        hasUserActivation: () => options.activated ?? false,
        openExternal,
        onExternalOpenBlocked,
        now: () => clock.now,
    })
    return { route, posted, onDataRequest, onNavigate, onCommentActivate, openExternal, onExternalOpenBlocked, clock }
}

const dataRequest = (method: string, payload: unknown = {}): CanvasToHostMessage =>
    ({ channel: 'posthog-canvas', type: 'data-request', id: 'r1', method, payload }) as CanvasToHostMessage

describe('createCanvasHostMessageRouter', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    test.each([
        ['actionInvoke', false, 'Canvas actions require a user action'],
        ['agentRequest', false, 'Agent requests require a user action'],
        ['actionInvoke', true, null],
        ['agentRequest', true, null],
        ['query', false, null],
    ])('%s with user activation %s is rejected with %s', async (method, activated, error) => {
        const { route, posted, onDataRequest } = setup({ activated })

        await route(dataRequest(method))

        expect(onDataRequest).toHaveBeenCalledTimes(error ? 0 : 1)
        expect(posted).toEqual([
            error
                ? { channel: 'posthog-canvas', type: 'data-response', id: 'r1', ok: false, error }
                : { channel: 'posthog-canvas', type: 'data-response', id: 'r1', ok: true, result: { ok: true } },
        ])
    })

    test('rejects a payload over the size cap without calling the host', async () => {
        const { route, posted, onDataRequest } = setup()

        await route(dataRequest('query', { hogql: 'x'.repeat(MAX_DATA_REQUEST_BYTES) }))

        expect(onDataRequest).not.toHaveBeenCalled()
        expect(posted[0]).toMatchObject({ ok: false, error: 'Canvas data request exceeds runtime limits' })
    })

    test('caps concurrent reads and frees the slot when one settles', async () => {
        const releases: (() => void)[] = []
        const { route, posted } = setup({
            onDataRequest: () => new Promise((resolve) => releases.push(() => resolve('done'))),
        })

        const inFlight = Array.from({ length: 8 }, () => route(dataRequest('query')))
        await route(dataRequest('query'))
        expect(posted).toEqual([
            expect.objectContaining({ ok: false, error: 'Canvas data request exceeds runtime limits' }),
        ])

        releases.forEach((release) => release())
        await Promise.all(inFlight)
        const afterRelease = route(dataRequest('query'))
        expect(releases).toHaveLength(9)
        releases[8]()
        await afterRelease
        expect(posted.filter((message) => 'ok' in message && message.ok)).toHaveLength(9)
    })

    test.each([
        ['query', true],
        ['connectorCall', false],
        ['agentRequest', false],
    ])('a hung %s times out: %s', async (method, timesOut) => {
        jest.useFakeTimers()
        const { route, posted } = setup({ activated: true, onDataRequest: () => new Promise(() => {}) })

        void route(dataRequest(method))
        await jest.advanceTimersByTimeAsync(DATA_REQUEST_TIMEOUT_MS)

        expect(posted).toEqual(
            timesOut ? [expect.objectContaining({ ok: false, error: 'Canvas data request timed out' })] : []
        )
    })

    test('reports a host failure as an error response', async () => {
        const { route, posted } = setup({
            onDataRequest: async () => {
                throw new Error('Unknown data method "nope"')
            },
        })

        await route(dataRequest('query'))

        expect(posted[0]).toMatchObject({ ok: false, error: 'Unknown data method "nope"' })
    })

    test.each([
        ['an unknown method', { type: 'data-request', id: 'r1', method: 'deleteProject', payload: {} }],
        ['a non-allowlisted navigation', { type: 'navigate', nav: { target: 'settings' } }],
        ['a non-PostHog external URL', { type: 'open-external', url: 'https://evil.example.com' }],
        ['another channel', { type: 'ready', channel: 'other' }],
    ])('the schema drops %s', (_, message) => {
        expect(canvasToHostMessageSchema.safeParse({ channel: 'posthog-canvas', ...message }).success).toBe(false)
    })

    test.each([
        ['connect', { target: 'connect', provider: 'github' }, false, false],
        ['connect', { target: 'connect', provider: 'github' }, true, true],
        ['canvas', { target: 'canvas', dashboardId: 'c1' }, false, true],
    ])('navigate to %s with user activation %s reaches the host: %s', async (_, nav, activated, forwarded) => {
        const { route, onNavigate } = setup({ activated })

        await route({ channel: 'posthog-canvas', type: 'navigate', nav } as CanvasToHostMessage)

        expect(onNavigate).toHaveBeenCalledTimes(forwarded ? 1 : 0)
    })

    test.each([
        ['with the clicked line', { top: 10, right: 90, bottom: 30, left: 20 }],
        ['from a build that reports no line', undefined],
    ])('comment-activate %s reaches the host', async (_, rect) => {
        const { route, onCommentActivate } = setup()
        const message = canvasToHostMessageSchema.parse({
            channel: 'posthog-canvas',
            type: 'comment-activate',
            id: 'thread-1',
            ...(rect ? { rect } : {}),
        })

        await route(message)

        expect(onCommentActivate).toHaveBeenCalledWith('thread-1', rect ?? null)
    })

    test('open-external needs a gesture and is throttled', async () => {
        const blocked = setup({ activated: false })
        await blocked.route({ channel: 'posthog-canvas', type: 'open-external', url: 'https://posthog.com/docs' })
        expect(blocked.openExternal).not.toHaveBeenCalled()
        expect(blocked.onExternalOpenBlocked).toHaveBeenCalledWith('https://posthog.com/docs', 'no-interaction')

        const { route, openExternal, onExternalOpenBlocked, clock } = setup({ activated: true })
        const open: CanvasToHostMessage = {
            channel: 'posthog-canvas',
            type: 'open-external',
            url: 'https://posthog.com/docs',
        }
        await route(open)
        await route(open)
        clock.now += EXTERNAL_OPEN_MIN_INTERVAL_MS
        await route(open)

        expect(openExternal).toHaveBeenCalledTimes(2)
        expect(onExternalOpenBlocked).toHaveBeenCalledWith('https://posthog.com/docs', 'throttled')
    })
})

import { EventEmitter } from 'node:events'

import {
    personhogConnectionEstablishmentSeconds,
    personhogConnectionState,
    personhogConnectionStateTransitionsTotal,
    personhogStreamAcquisitionSeconds,
    personhogStreamsInFlight,
} from './metrics'
import { type SessionState, SessionStateMonitor } from './session-state-monitor'

jest.mock('./metrics', () => ({
    personhogConnectionState: {
        labels: jest.fn().mockReturnValue({ set: jest.fn() }),
    },
    personhogConnectionStateTransitionsTotal: {
        labels: jest.fn().mockReturnValue({ inc: jest.fn() }),
    },
    personhogConnectionEstablishmentSeconds: {
        labels: jest.fn().mockReturnValue({ observe: jest.fn() }),
    },
    personhogStreamsInFlight: {
        labels: jest.fn().mockReturnValue({ inc: jest.fn(), dec: jest.fn() }),
    },
    personhogStreamAcquisitionSeconds: {
        labels: jest.fn().mockReturnValue({ observe: jest.fn() }),
    },
}))

const mockStateGauge = personhogConnectionState as jest.Mocked<typeof personhogConnectionState>
const mockTransitions = personhogConnectionStateTransitionsTotal as jest.Mocked<
    typeof personhogConnectionStateTransitionsTotal
>
const mockEstablishment = personhogConnectionEstablishmentSeconds as jest.Mocked<
    typeof personhogConnectionEstablishmentSeconds
>
const mockStreamsInFlight = personhogStreamsInFlight as jest.Mocked<typeof personhogStreamsInFlight>
const mockStreamAcquisition = personhogStreamAcquisitionSeconds as jest.Mocked<typeof personhogStreamAcquisitionSeconds>

function makeMockStream(): EventEmitter {
    return new EventEmitter()
}

function makeMockSessionManager(initialState: SessionState = 'closed') {
    let currentState: SessionState = initialState
    const defaultStream = makeMockStream()
    return {
        get authority() {
            return 'http://localhost:50051'
        },
        state: () => currentState,
        setState: (s: SessionState) => {
            currentState = s
        },
        request: jest.fn().mockResolvedValue(defaultStream),
        defaultStream,
        notifyResponseByteRead: jest.fn(),
        connect: jest.fn(),
        abort: jest.fn(),
    }
}

describe('SessionStateMonitor', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.clearAllMocks()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('sets initial state gauge on construction', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)

        expect(mockStateGauge.labels).toHaveBeenCalledWith({ state: 'closed', client: 'test-client' })
        expect(mockStateGauge.labels({ state: 'closed', client: 'test-client' }).set).toHaveBeenCalledWith(1)

        monitor.close()
    })

    it('tracks state transitions on poll', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)
        jest.clearAllMocks()

        inner.setState('connecting')
        jest.advanceTimersByTime(1000)

        expect(mockTransitions.labels).toHaveBeenCalledWith({
            from_state: 'closed',
            to_state: 'connecting',
            client: 'test-client',
        })
        expect(
            mockTransitions.labels({ from_state: 'closed', to_state: 'connecting', client: 'test-client' }).inc
        ).toHaveBeenCalled()

        monitor.close()
    })

    it.each<SessionState>(['open', 'idle'])(
        'tracks connection establishment latency (connecting -> %s)',
        (targetState) => {
            const inner = makeMockSessionManager('closed')
            const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)

            inner.setState('connecting')
            jest.advanceTimersByTime(1000)

            inner.setState(targetState)
            jest.advanceTimersByTime(1000)

            expect(mockEstablishment.labels).toHaveBeenCalledWith({ client: 'test-client' })
            expect(mockEstablishment.labels({ client: 'test-client' }).observe).toHaveBeenCalledTimes(1)
            const latency = (mockEstablishment.labels({ client: 'test-client' }).observe as jest.Mock).mock.calls[0][0]
            expect(latency).toBeGreaterThanOrEqual(0)

            monitor.close()
        }
    )

    it('does not record latency when connecting transitions to error', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)

        inner.setState('connecting')
        jest.advanceTimersByTime(1000)

        inner.setState('error')
        jest.advanceTimersByTime(1000)

        expect(mockEstablishment.labels({ client: 'test-client' }).observe).not.toHaveBeenCalled()

        monitor.close()
    })

    it('does not record latency for open without prior connecting', () => {
        const inner = makeMockSessionManager('idle')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)

        inner.setState('open')
        jest.advanceTimersByTime(1000)

        expect(mockEstablishment.labels({ client: 'test-client' }).observe).not.toHaveBeenCalled()

        monitor.close()
    })

    it('tracks reconnection latency across multiple cycles', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)

        // First connection
        inner.setState('connecting')
        jest.advanceTimersByTime(1000)
        inner.setState('open')
        jest.advanceTimersByTime(1000)

        // Disconnect and reconnect
        inner.setState('closed')
        jest.advanceTimersByTime(1000)
        inner.setState('connecting')
        jest.advanceTimersByTime(1000)
        inner.setState('idle')
        jest.advanceTimersByTime(1000)

        expect(mockEstablishment.labels({ client: 'test-client' }).observe).toHaveBeenCalledTimes(2)

        monitor.close()
    })

    it('detects transitions around request() calls', async () => {
        const inner = makeMockSessionManager('idle')
        // Use a very long poll interval so only request() detects the change
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)
        jest.clearAllMocks()

        inner.setState('open')
        await monitor.request('POST', '/test', {}, {})

        expect(mockTransitions.labels).toHaveBeenCalledWith({
            from_state: 'idle',
            to_state: 'open',
            client: 'test-client',
        })

        monitor.close()
    })

    it('detects transitions when request() throws', async () => {
        const inner = makeMockSessionManager('idle')
        inner.request.mockRejectedValueOnce(new Error('connection lost'))
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)
        jest.clearAllMocks()

        inner.setState('error')
        await expect(monitor.request('POST', '/test', {}, {})).rejects.toThrow('connection lost')

        expect(mockTransitions.labels).toHaveBeenCalledWith({
            from_state: 'idle',
            to_state: 'error',
            client: 'test-client',
        })

        monitor.close()
    })

    it('ignores same-state polls', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)
        jest.clearAllMocks()

        // Multiple polls with no state change
        jest.advanceTimersByTime(5000)

        expect(mockTransitions.labels).not.toHaveBeenCalled()

        monitor.close()
    })

    it('close() stops polling', () => {
        const inner = makeMockSessionManager('closed')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 1000)
        monitor.close()
        jest.clearAllMocks()

        inner.setState('connecting')
        jest.advanceTimersByTime(5000)

        expect(mockTransitions.labels).not.toHaveBeenCalled()
    })

    it('records stream acquisition time on successful request', async () => {
        const inner = makeMockSessionManager('open')
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)

        await monitor.request('POST', '/test', {}, {})

        expect(mockStreamAcquisition.labels).toHaveBeenCalledWith({ client: 'test-client' })
        const observedValue = (mockStreamAcquisition.labels({ client: 'test-client' }).observe as jest.Mock).mock
            .calls[0][0]
        expect(observedValue).toBeGreaterThanOrEqual(0)

        monitor.close()
    })

    it('records stream acquisition time on failed request', async () => {
        const inner = makeMockSessionManager('open')
        inner.request.mockRejectedValueOnce(new Error('connect failed'))
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)

        await expect(monitor.request('POST', '/test', {}, {})).rejects.toThrow('connect failed')

        expect(mockStreamAcquisition.labels).toHaveBeenCalledWith({ client: 'test-client' })
        expect(mockStreamAcquisition.labels({ client: 'test-client' }).observe).toHaveBeenCalledTimes(1)

        monitor.close()
    })

    it('increments in-flight gauge on request and decrements on stream close', async () => {
        const stream = makeMockStream()
        const inner = makeMockSessionManager('open')
        inner.request.mockResolvedValueOnce(stream)
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)
        jest.clearAllMocks()

        await monitor.request('POST', '/test', {}, {})

        expect(mockStreamsInFlight.labels({ client: 'test-client' }).inc).toHaveBeenCalledTimes(1)
        expect(mockStreamsInFlight.labels({ client: 'test-client' }).dec).not.toHaveBeenCalled()

        stream.emit('close')

        expect(mockStreamsInFlight.labels({ client: 'test-client' }).dec).toHaveBeenCalledTimes(1)

        monitor.close()
    })

    it('tracks multiple concurrent streams independently', async () => {
        const stream1 = makeMockStream()
        const stream2 = makeMockStream()
        const inner = makeMockSessionManager('open')
        inner.request.mockResolvedValueOnce(stream1).mockResolvedValueOnce(stream2)
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)
        jest.clearAllMocks()

        await monitor.request('POST', '/test1', {}, {})
        await monitor.request('POST', '/test2', {}, {})

        expect(mockStreamsInFlight.labels({ client: 'test-client' }).inc).toHaveBeenCalledTimes(2)

        stream1.emit('close')
        expect(mockStreamsInFlight.labels({ client: 'test-client' }).dec).toHaveBeenCalledTimes(1)

        stream2.emit('close')
        expect(mockStreamsInFlight.labels({ client: 'test-client' }).dec).toHaveBeenCalledTimes(2)

        monitor.close()
    })

    it('does not increment in-flight gauge when request fails', async () => {
        const inner = makeMockSessionManager('open')
        inner.request.mockRejectedValueOnce(new Error('refused'))
        const monitor = new SessionStateMonitor(inner as any, 'test-client', 600_000)
        jest.clearAllMocks()

        await expect(monitor.request('POST', '/test', {}, {})).rejects.toThrow('refused')

        expect(mockStreamsInFlight.labels({ client: 'test-client' }).inc).not.toHaveBeenCalled()

        monitor.close()
    })
})

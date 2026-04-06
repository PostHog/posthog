import type { GrpcTransportOptions } from '@connectrpc/connect-node'
import { Http2SessionManager } from '@connectrpc/connect-node'
import * as http2 from 'node:http2'

import {
    personhogConnectionEstablishmentSeconds,
    personhogConnectionState,
    personhogConnectionStateTransitionsTotal,
    personhogStreamAcquisitionSeconds,
    personhogStreamsInFlight,
} from './metrics'

export type SessionState = 'closed' | 'connecting' | 'open' | 'idle' | 'verifying' | 'error'

const ALL_STATES: SessionState[] = ['closed', 'connecting', 'open', 'idle', 'verifying', 'error']

/**
 * Wraps an Http2SessionManager to monitor connection state transitions and
 * emit Prometheus metrics.
 *
 * Because @connectrpc's Http2SessionManager has no subscribe/callback API for
 * state changes, we detect
 * transitions by:
 *   1. Polling state() on a configurable interval (catches async transitions
 *      like idle timeouts, ping failures, goaway).
 *   2. Checking state before/after each request() call (catches transitions
 *      triggered by RPC activity with no polling delay).
 */
type SessionManager = NonNullable<GrpcTransportOptions['sessionManager']>

export class SessionStateMonitor implements SessionManager {
    private readonly inner: Http2SessionManager

    private previousState: SessionState
    private connectingStartedAt: number | undefined
    private pollTimer: ReturnType<typeof setInterval> | undefined
    private readonly clientName: string

    constructor(inner: Http2SessionManager, clientName: string, pollIntervalMs: number = 5_000) {
        this.inner = inner
        this.clientName = clientName
        this.previousState = inner.state()
        this.setStateGauge(this.previousState)
        this.pollTimer = setInterval(() => this.checkStateTransition(), pollIntervalMs)
        this.pollTimer.unref()
    }

    /**
     * Implements NodeHttp2ClientSessionManager.authority
     */
    get authority(): string {
        return this.inner.authority
    }

    /**
     * Implements NodeHttp2ClientSessionManager.request — delegates to the inner
     * manager and checks for state transitions around the call.
     *
     * Instruments:
     * - Stream acquisition time: how long this.inner.request() takes (includes
     *   connection establishment if the session isn't ready).
     * - Streams in flight: gauge of concurrently open HTTP/2 streams, decremented
     *   when the stream emits 'close'.
     */
    async request(
        method: string,
        path: string,
        headers: http2.OutgoingHttpHeaders,
        options: Omit<http2.ClientSessionRequestOptions, 'signal'>
    ): Promise<http2.ClientHttp2Stream> {
        this.checkStateTransition()
        const acquireStart = performance.now()
        try {
            const stream = await this.inner.request(method, path, headers, options)
            const acquireDurationSecs = (performance.now() - acquireStart) / 1000
            personhogStreamAcquisitionSeconds.labels({ client: this.clientName }).observe(acquireDurationSecs)

            personhogStreamsInFlight.labels({ client: this.clientName }).inc()
            stream.once('close', () => {
                personhogStreamsInFlight.labels({ client: this.clientName }).dec()
            })

            this.checkStateTransition()
            return stream
        } catch (error) {
            const acquireDurationSecs = (performance.now() - acquireStart) / 1000
            personhogStreamAcquisitionSeconds.labels({ client: this.clientName }).observe(acquireDurationSecs)
            this.checkStateTransition()
            throw error
        }
    }

    /**
     * Implements NodeHttp2ClientSessionManager.notifyResponseByteRead
     */
    notifyResponseByteRead(stream: http2.ClientHttp2Stream): void {
        this.inner.notifyResponseByteRead(stream)
    }

    /**
     * Returns the current state from the inner session manager.
     */
    state(): SessionState {
        return this.inner.state()
    }

    /**
     * Stop polling. Only used in tests today — no server lifecycle calls this.
     * Does not call inner.abort() because the transport owns the session
     * lifecycle; if we wire this into server shutdown, abort should be added.
     */
    close(): void {
        if (this.pollTimer) {
            clearInterval(this.pollTimer)
            this.pollTimer = undefined
        }
    }

    private checkStateTransition(): void {
        const current = this.inner.state()
        if (current === this.previousState) {
            return
        }
        const prev = this.previousState
        this.previousState = current

        // Emit transition counter
        personhogConnectionStateTransitionsTotal
            .labels({ from_state: prev, to_state: current, client: this.clientName })
            .inc()

        // Update state gauge
        this.setStateGauge(current)

        // Track connection establishment latency
        if (current === 'connecting') {
            this.connectingStartedAt = performance.now()
        } else if ((current === 'open' || current === 'idle') && this.connectingStartedAt !== undefined) {
            const durationMs = performance.now() - this.connectingStartedAt
            personhogConnectionEstablishmentSeconds.labels({ client: this.clientName }).observe(durationMs / 1000)
            this.connectingStartedAt = undefined
        } else if (current === 'error' || current === 'closed') {
            this.connectingStartedAt = undefined
        }
    }

    private setStateGauge(activeState: SessionState): void {
        for (const s of ALL_STATES) {
            personhogConnectionState.labels({ state: s, client: this.clientName }).set(s === activeState ? 1 : 0)
        }
    }
}

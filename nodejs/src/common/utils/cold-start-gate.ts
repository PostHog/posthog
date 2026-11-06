type OriginWarmth = { warmUntil: number; probe: Promise<void> | null }

export type ColdStartAdmission = { probe: boolean; release: () => void }

const MAX_TRACKED_ORIGINS = 10_000

/**
 * Holds a burst of requests to a cold origin behind one probe request. undici sizes its pool before ALPN tells it
 * the protocol, so without the gate a burst to a cold HTTP/2 origin opens one session per request. The probe's
 * response headers mean the origin's SETTINGS frame has arrived, so the released requests multiplex on that
 * session. An origin that negotiates HTTP/1.1 still gets one connection per released request. An origin counts as
 * warm until the dispatcher's idle timeout has passed since its last response activity, which is when undici closes
 * the idle session. A session the origin closes earlier, with a GOAWAY, still counts as warm, so a burst inside that
 * window fans out up to the pool cap.
 */
export class ColdStartGate {
    private readonly origins = new Map<string, OriginWarmth>()
    private nextSweepAt = 0

    constructor(private readonly idleTimeoutMs: number) {}

    /**
     * Resolves once the request may start. `release` frees the held requests and must run when the probe has
     * response headers or has failed; for a request that is not the probe it does nothing. A held request whose
     * signal aborts rejects with the signal's reason, as undici does for a request it never sent. When a probe fails,
     * the next waiter becomes the probe, so a burst does not fan out after one failed connection.
     */
    async acquire(origin: string, signal?: AbortSignal): Promise<ColdStartAdmission> {
        for (;;) {
            const now = Date.now()
            const state = this.origins.get(origin)
            if (state?.probe) {
                await this.waitForProbe(state.probe, signal)
                continue
            }
            if (state && state.warmUntil > now) {
                return { probe: false, release: () => {} }
            }
            let releaseProbe!: () => void
            const probe = new Promise<void>((resolve) => (releaseProbe = resolve))
            const probing: OriginWarmth = { warmUntil: state?.warmUntil ?? 0, probe }
            this.origins.set(origin, probing)
            this.sweep(now)
            return {
                probe: true,
                release: () => {
                    if (probing.probe === probe) {
                        probing.probe = null
                    }
                    releaseProbe()
                },
            }
        }
    }

    touch(origin: string): void {
        const warmUntil = Date.now() + this.idleTimeoutMs
        const state = this.origins.get(origin)
        if (state) {
            state.warmUntil = warmUntil
        } else {
            this.origins.set(origin, { warmUntil, probe: null })
        }
    }

    private async waitForProbe(probe: Promise<void>, signal?: AbortSignal): Promise<void> {
        if (!signal) {
            await probe
            return
        }
        if (signal.aborted) {
            throw signal.reason
        }
        let onAbort!: () => void
        const aborted = new Promise<never>((_, reject) => {
            onAbort = () => reject(signal.reason)
            signal.addEventListener('abort', onAbort, { once: true })
        })
        try {
            await Promise.race([probe, aborted])
        } finally {
            signal.removeEventListener('abort', onAbort)
        }
    }

    private sweep(now: number): void {
        if (this.origins.size < MAX_TRACKED_ORIGINS || now < this.nextSweepAt) {
            return
        }
        this.nextSweepAt = now + 1000
        for (const [origin, state] of this.origins) {
            if (!state.probe && state.warmUntil <= now) {
                this.origins.delete(origin)
            }
        }
    }
}

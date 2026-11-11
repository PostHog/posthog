type AddressHealth = {
    windowStartedAt: number
    requests: number
    failures: number
    // 0 while closed. While open, the time the pause ends. After that time the address is half-open: the next
    // outcome closes it or opens it again.
    openUntil: number
}

export type IpCircuitBreakerOptions = {
    minFailures: number
    failureRatio: number
    windowMs: number
    cooldownMs: number
}

export type IpCircuitRejection = { address: string; retryInMs: number }

const MAX_TRACKED_ADDRESSES = 10_000

/**
 * Pauses requests to a destination IP address after many recent requests to it failed in a way that discards the
 * connection. A request that times out, fails to connect, or gets `Connection: close` cannot reuse its socket, so the
 * next request opens a new connection. Behind a NAT gateway each new connection takes a source port for that
 * destination IP and port, and a gateway IP has about 55,000 of them. One failing origin can use all the ports, and
 * then requests to every other host on the same IP fail too. The key is the IP address and not the hostname, because
 * the port limit applies per IP and many hostnames can share one IP.
 */
export class IpCircuitBreaker {
    private readonly addresses = new Map<string, AddressHealth>()
    private nextSweepAt = 0

    constructor(private readonly options: IpCircuitBreakerOptions) {}

    /**
     * Returns null when the request may start. A hostname can resolve to several addresses and the connection can use
     * any of them, so the request is rejected only when every address is open.
     */
    check(addresses: string[]): IpCircuitRejection | null {
        const now = Date.now()
        let rejection: IpCircuitRejection | null = null
        for (const address of addresses) {
            const openUntil = this.addresses.get(address)?.openUntil ?? 0
            if (openUntil <= now) {
                return null
            }
            if (!rejection || openUntil - now < rejection.retryInMs) {
                rejection = { address, retryInMs: openUntil - now }
            }
        }
        return rejection
    }

    /** Records one request outcome against every address of its hostname. Returns how many addresses it opened. */
    record(addresses: string[], failed: boolean): number {
        const now = Date.now()
        let opened = 0
        for (const address of addresses) {
            let health = this.addresses.get(address)
            if (!health) {
                if (!failed) {
                    continue
                }
                health = { windowStartedAt: now, requests: 0, failures: 0, openUntil: 0 }
                this.addresses.set(address, health)
                this.sweep(now)
            }
            if (health.openUntil > now) {
                // A request that started before the address opened. It says nothing new.
                continue
            }
            if (health.openUntil !== 0) {
                health.openUntil = failed ? now + this.options.cooldownMs : 0
                opened += failed ? 1 : 0
                this.resetWindow(health, now)
                continue
            }
            if (now - health.windowStartedAt >= this.options.windowMs) {
                this.resetWindow(health, now)
            }
            health.requests++
            health.failures += failed ? 1 : 0
            if (
                health.failures >= this.options.minFailures &&
                health.failures >= health.requests * this.options.failureRatio
            ) {
                health.openUntil = now + this.options.cooldownMs
                opened++
                this.resetWindow(health, now)
            }
        }
        return opened
    }

    private resetWindow(health: AddressHealth, now: number): void {
        health.windowStartedAt = now
        health.requests = 0
        health.failures = 0
    }

    private sweep(now: number): void {
        if (this.addresses.size < MAX_TRACKED_ADDRESSES || now < this.nextSweepAt) {
            return
        }
        this.nextSweepAt = now + 1000
        for (const [address, health] of this.addresses) {
            if (health.openUntil === 0 && now - health.windowStartedAt >= this.options.windowMs) {
                this.addresses.delete(address)
            }
        }
    }
}

interface Waiter {
    bytes: number
    grant: () => void
}

// Limits the compressed recording bytes that renders on this worker load at the same time. A few large
// recordings that load together push the pod past its memory limit, and the OOM kill stops every render on it.
export class ByteBudget {
    private inFlight = 0
    private readonly queue: Waiter[] = []

    constructor(private readonly limit: number) {}

    get inFlightBytes(): number {
        return this.inFlight
    }

    // Grants are first in, first out, so a stream of small renders cannot starve a large one.
    // A request larger than the whole budget runs when nothing else is in flight.
    acquire(bytes: number, signal?: AbortSignal): Promise<() => void> {
        signal?.throwIfAborted()
        if (this.queue.length === 0 && this.fits(bytes)) {
            this.inFlight += bytes
            return Promise.resolve(this.releaser(bytes))
        }
        return new Promise((resolve, reject) => {
            const onAbort = (): void => {
                this.queue.splice(this.queue.indexOf(waiter), 1)
                this.drain()
                reject(signal?.reason)
            }
            const waiter: Waiter = {
                bytes,
                grant: () => {
                    signal?.removeEventListener('abort', onAbort)
                    resolve(this.releaser(bytes))
                },
            }
            signal?.addEventListener('abort', onAbort, { once: true })
            this.queue.push(waiter)
        })
    }

    private fits(bytes: number): boolean {
        return this.inFlight === 0 || this.inFlight + bytes <= this.limit
    }

    private drain(): void {
        while (this.queue.length > 0 && this.fits(this.queue[0].bytes)) {
            const next = this.queue.shift()!
            this.inFlight += next.bytes
            next.grant()
        }
    }

    private releaser(bytes: number): () => void {
        let released = false
        return () => {
            if (released) {
                return
            }
            released = true
            this.inFlight -= bytes
            this.drain()
        }
    }
}

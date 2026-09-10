/**
 * A driveable EventSource stand-in for tests. jsdom ships no EventSource at all, and the wizard sync
 * transports need one a test can step frame by frame: open, data frames, named events (`stream-end`,
 * the server's `error` payload) and browser transport failures, which differ only by readyState.
 *
 * Handlers registered both ways are invoked, since the transports use `onmessage`/`onerror`
 * assignment for data and `addEventListener` for named events.
 */
export class MockEventSource {
    static readonly CONNECTING = 0
    static readonly OPEN = 1
    static readonly CLOSED = 2

    /** Every source opened since the last `reset()`, in order — the count is how many connects happened. */
    static instances: MockEventSource[] = []

    readyState: number = MockEventSource.CONNECTING
    onopen: ((event: Event) => void) | null = null
    onmessage: ((event: MessageEvent) => void) | null = null
    onerror: ((event: Event) => void) | null = null

    private listeners = new Map<string, ((event: Event) => void)[]>()

    constructor(readonly url: string) {
        MockEventSource.instances.push(this)
    }

    static reset(): void {
        MockEventSource.instances = []
    }

    static last(): MockEventSource {
        const source = MockEventSource.instances[MockEventSource.instances.length - 1]
        if (!source) {
            throw new Error('No EventSource was opened')
        }
        return source
    }

    addEventListener(name: string, handler: (event: Event) => void): void {
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler])
    }

    removeEventListener(name: string, handler: (event: Event) => void): void {
        this.listeners.set(
            name,
            (this.listeners.get(name) ?? []).filter((h) => h !== handler)
        )
    }

    close(): void {
        this.readyState = MockEventSource.CLOSED
    }

    emitOpen(): void {
        this.readyState = MockEventSource.OPEN
        const event = new Event('open')
        this.onopen?.(event)
        this.dispatch('open', event)
    }

    /** An unnamed data frame, the shape both transports read run/session state from. */
    emitMessage(data: string): void {
        const event = new MessageEvent('message', { data })
        this.onmessage?.(event)
        this.dispatch('message', event)
    }

    /** A named event. With `data` it is a MessageEvent, which is what tells a server-sent
     * `error` apart from a transport failure. */
    emitNamed(name: string, data?: string): void {
        const event = data === undefined ? new Event(name) : new MessageEvent(name, { data })
        if (name === 'error') {
            this.onerror?.(event)
        }
        this.dispatch(name, event)
    }

    /** A browser transport failure. CLOSED means the browser gave up and will not retry on its own. */
    emitTransportError(readyState: number = MockEventSource.CLOSED): void {
        this.readyState = readyState
        this.emitNamed('error')
    }

    private dispatch(name: string, event: Event): void {
        for (const handler of this.listeners.get(name) ?? []) {
            handler(event)
        }
    }
}

/** Swap the global in for a test. Returns the restore function. */
export function installMockEventSource(): () => void {
    const original = (global as any).EventSource
    MockEventSource.reset()
    ;(global as any).EventSource = MockEventSource
    return () => {
        ;(global as any).EventSource = original
    }
}

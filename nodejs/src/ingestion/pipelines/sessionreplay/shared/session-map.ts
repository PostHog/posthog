/**
 * Collections keyed by a `(teamId, sessionId)` pair.
 *
 * A plain `Map`/`Set` keys objects by reference, so it can't look a session up by a freshly-built
 * pair. These wrap a `Map` with a composite string key and keep that encoding private, so callers
 * pass `(teamId, sessionId)` and never depend on the key format. Safe because `teamId` is numeric and
 * `sessionId` is capture-restricted to `[A-Za-z0-9-]`, so the `:` separator can't be ambiguous.
 */

function encode(teamId: number, sessionId: string): string {
    return `${teamId}:${sessionId}`
}

export class SessionMap<V> {
    private readonly byKey = new Map<string, V>()

    get(teamId: number, sessionId: string): V | undefined {
        return this.byKey.get(encode(teamId, sessionId))
    }

    set(teamId: number, sessionId: string, value: V): this {
        this.byKey.set(encode(teamId, sessionId), value)
        return this
    }

    has(teamId: number, sessionId: string): boolean {
        return this.byKey.has(encode(teamId, sessionId))
    }

    delete(teamId: number, sessionId: string): boolean {
        return this.byKey.delete(encode(teamId, sessionId))
    }

    get size(): number {
        return this.byKey.size
    }

    values(): IterableIterator<V> {
        return this.byKey.values()
    }
}

export class SessionSet implements Iterable<{ teamId: number; sessionId: string }> {
    private readonly sessions = new SessionMap<{ teamId: number; sessionId: string }>()

    add(teamId: number, sessionId: string): this {
        this.sessions.set(teamId, sessionId, { teamId, sessionId })
        return this
    }

    has(teamId: number, sessionId: string): boolean {
        return this.sessions.has(teamId, sessionId)
    }

    get size(): number {
        return this.sessions.size
    }

    [Symbol.iterator](): Iterator<{ teamId: number; sessionId: string }> {
        return this.sessions.values()
    }
}

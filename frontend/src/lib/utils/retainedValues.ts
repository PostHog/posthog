import { getContext } from 'kea'

import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

type Entry<T> = { value: T; expiresAt: number }

export class RetainedValues<T> {
    private readonly stores = new WeakMap<ReturnType<typeof getContext>, Map<string, Entry<T>>>()

    constructor(
        private readonly maxEntries: number,
        private readonly ttlMs: number
    ) {}

    get(id: string): T | null {
        const key = this.key(id)
        if (!key) {
            return null
        }
        const store = this.store()
        const entry = store.get(key)
        if (!entry || entry.expiresAt <= Date.now()) {
            store.delete(key)
            return null
        }
        return entry.value
    }

    set(id: string, value: T): void {
        const key = this.key(id)
        if (!key) {
            return
        }
        const store = this.store()
        store.delete(key)
        store.set(key, { value, expiresAt: Date.now() + this.ttlMs })
        while (store.size > this.maxEntries) {
            store.delete(store.keys().next().value!)
        }
    }

    // Ids such as insight and notebook short ids are unique only within a project.
    private key(id: string): string | null {
        const teamId = getCurrentTeamIdOrNone()
        return teamId ? `${teamId}:${id}` : null
    }

    private store(): Map<string, Entry<T>> {
        const context = getContext()
        let store = this.stores.get(context)
        if (!store) {
            store = new Map()
            this.stores.set(context, store)
        }
        return store
    }
}

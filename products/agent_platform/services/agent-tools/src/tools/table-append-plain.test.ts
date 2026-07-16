import { describe, expect, it } from 'vitest'

import type { TabularStore, ToolContext } from '@posthog/agent-shared'

import { tableAppendV1 } from './table'

// Records the options passed to `append` so we can assert whether dedupe was
// forwarded. A cross-tenant (authenticated-audience) store must force PLAIN
// append — dedupe disabled — so the `skipped` count can't leak whether another
// (untrusted) caller already wrote a key.
function spyStore(): { store: TabularStore; lastDedupeOn: () => string | undefined } {
    let seen: string | undefined
    const store = {
        async append(_scope: unknown, _table: string, rows: unknown[], opts?: { dedupeOn?: string }) {
            seen = opts?.dedupeOn
            return { appended: (rows as unknown[]).length, skipped: 0 }
        },
    } as unknown as TabularStore
    return { store, lastDedupeOn: () => seen }
}

function ctx(store: TabularStore, crossTenantStore: boolean): ToolContext {
    return { teamId: 1, applicationId: 'app-1', tabularStore: store, crossTenantStore } as unknown as ToolContext
}

describe('table-append cross-tenant plain-append', () => {
    it('forwards dedupe_on on a normal (single-tenant) store', async () => {
        const { store, lastDedupeOn } = spyStore()
        await tableAppendV1.run({ table: 't', rows: [{ k: 'a' }], dedupe_on: 'k' }, ctx(store, false))
        expect(lastDedupeOn()).toBe('k')
    })

    it('drops dedupe_on on a cross-tenant (authenticated) store — closes the skipped-count oracle', async () => {
        const { store, lastDedupeOn } = spyStore()
        await tableAppendV1.run({ table: 't', rows: [{ k: 'a' }], dedupe_on: 'k' }, ctx(store, true))
        expect(lastDedupeOn()).toBeUndefined()
    })
})

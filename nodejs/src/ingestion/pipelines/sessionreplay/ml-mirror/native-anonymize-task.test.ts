import { AsyncLocalStorage } from 'node:async_hooks'
import { setFlagsFromString } from 'node:v8'
import { runInNewContext } from 'node:vm'

import { logger } from '~/common/utils/logger'

let rustAddon: typeof import('@posthog/replay-anonymizer') | null = null
try {
    rustAddon = require('@posthog/replay-anonymizer')
} catch (e) {
    if (process.env.CI) {
        throw new Error(`replay-anonymizer addon failed to load; the native task test cannot run in CI: ${String(e)}`)
    }
    logger.warn('🙈', 'replay_anonymizer_addon_not_built_skipping_native_task_test')
}

const describeAddon = rustAddon ? describe : describe.skip
describeAddon('native anonymize task', () => {
    setFlagsFromString('--expose-gc')
    const gc = runInNewContext('gc') as () => void
    const nextMacrotask = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

    function payload(): Buffer {
        const inner = JSON.stringify({
            event: '$snapshot_items',
            properties: {
                $snapshot_items: [
                    {
                        type: 2,
                        timestamp: 1_700_000_000_000,
                        data: { node: { type: 0, childNodes: [] }, initialOffset: { top: 0, left: 0 } },
                    },
                ],
                $session_id: 's-1',
                $window_id: 'w',
            },
        })
        return Buffer.from(JSON.stringify({ distinct_id: 'd-1', data: inner }))
    }

    const storage = new AsyncLocalStorage<{ id: number }>()

    // A store created in the test body would stay reachable from the suspended test function itself.
    async function anonymizeWithinStore(id: number, stores: WeakRef<{ id: number }>[]): Promise<void> {
        const store = { id }
        stores.push(new WeakRef(store))
        const result = await storage.run(store, () => rustAddon!.anonymizeKafkaPayload(payload()))
        expect(result.failed).toBe(false)
    }

    it('lets the async context of a finished call be collected', async () => {
        // Only a release build of the addon can fail this, because Neon deletes the async work inside
        // a debug assertion. CI builds the addon in release mode.
        rustAddon!.initAnonymizer({ text: [], url: [] })
        // The first call of a process keeps its context once, so it runs outside the measured stores.
        await rustAddon!.anonymizeKafkaPayload(payload())
        const stores: WeakRef<{ id: number }>[] = []
        for (let id = 0; id < 20; id++) {
            await anonymizeWithinStore(id, stores)
        }

        await nextMacrotask()
        gc()
        await nextMacrotask()

        expect(stores.map((store) => store.deref()?.id).filter((id) => id !== undefined)).toEqual([])
    })
})

import { Hub } from '../types'
import { PubSub } from '../utils/pubsub'
import { retryIfRetriable } from '../utils/retries'
import { status } from '../utils/status'
import { delay, sleep } from '../utils/utils'
import { setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'
import { populatePluginCapabilities } from './vm/lazy'

// If a reload is already scheduled, this will be a promise that resolves when the reload is done.
let RELOAD_PLUGINS_PROMISE: Promise<void> | undefined

// Whether the actual reload work has started. If `RELOAD_PLUGINS_PROMISE` is defined and this is
// `false` it means the promise is still sleeping for jitter, and so concurrent requests can know
// that a reload will start in the future.
let RELOAD_PLUGINS_PROMISE_STARTED = false

/**
 * Class for managing server wide tasks such as reloading plugins
 */
export class ServerTaskManager {
    private pubSub?: PubSub
    constructor(private hub: Hub) {}

    async start() {
        this.pubSub = new PubSub(this.hub, {
            [this.hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                await this.reloadPlugins()
            },
            'reset-available-product-features-cache': (message) => {
                this.resetAvailableProductFeaturesCache(JSON.parse(message))
            },
            'populate-plugin-capabilities': async (message) => {
                await this.populatePluginCapabilities(JSON.parse(message))
            },
        })

        await this.pubSub.start()
    }

    async reloadPlugins() {
        if (RELOAD_PLUGINS_PROMISE && !RELOAD_PLUGINS_PROMISE_STARTED) {
            // A reload is already scheduled and hasn't started yet. When it starts it will load the
            // state of plugins after this reload request was issued, so we're done here.
            return
        }

        if (RELOAD_PLUGINS_PROMISE && RELOAD_PLUGINS_PROMISE_STARTED) {
            // A reload was in progress, we need to wait for it to finish and then we can schedule a
            // new one (or a concurrent request will beat us to it after also waiting here, which is
            // fine!).
            await RELOAD_PLUGINS_PROMISE
        }

        if (!RELOAD_PLUGINS_PROMISE) {
            status.info('⚡', 'Reloading plugins!')
            // No reload is in progress, schedule one. If multiple concurrent requests got in line
            // above, we only need one to schedule the reload here.

            RELOAD_PLUGINS_PROMISE = (async () => {
                // Jitter the reload time to avoid all workers reloading at the same time.
                const jitterMs = Math.random() * this.hub.RELOAD_PLUGIN_JITTER_MAX_MS
                status.info('💤', `Sleeping for ${jitterMs}ms to jitter reloadPlugins`)
                await sleep(jitterMs)

                RELOAD_PLUGINS_PROMISE_STARTED = true
                try {
                    const tries = 3
                    const retrySleepMs = 5000
                    await retryIfRetriable(async () => await setupPlugins(this.hub), tries, retrySleepMs)
                } finally {
                    RELOAD_PLUGINS_PROMISE = undefined
                    RELOAD_PLUGINS_PROMISE_STARTED = false
                }
            })()

            await RELOAD_PLUGINS_PROMISE
        }
    }
    async teardownPlugins() {
        await teardownPlugins(this.hub)
    }
    async flushKafkaMessages() {
        await this.hub.kafkaProducer.flush()
    }
    resetAvailableProductFeaturesCache(args: { organization_id: string }) {
        this.hub.organizationManager.resetAvailableProductFeaturesCache(args.organization_id)
    }
    async populatePluginCapabilities(args: { plugin_id: string }) {
        if (!this.hub?.capabilities.appManagementSingleton) {
            return
        }
        await populatePluginCapabilities(this.hub, Number(args.plugin_id))
    }

    async shutdown() {
        await this.pubSub?.stop()
        // Wait *up to* 5 seconds to shut down VMs.
        await Promise.race([this.teardownPlugins(), delay(5000)])
        // Wait 2 seconds to flush the last queues and caches
        await Promise.all([this.flushKafkaMessages(), delay(2000)])
    }
}

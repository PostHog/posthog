import { Hub, PluginConfig } from '../types'
import { processError } from '../utils/db/error'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { pluginConfigIdFromStack, sleep } from '../utils/utils'
import { setupPlugins } from './plugins/setup'
import { TimeoutError } from './vm/vm'

// If a reload is already scheduled, this will be a promise that resolves when the reload is done.
let RELOAD_PLUGINS_PROMISE: Promise<void> | undefined

// Whether the actual reload work has started. If `RELOAD_PLUGINS_PROMISE` is defined and this is
// `false` it means the promise is still sleeping for jitter, and so concurrent requests can know
// that a reload will start in the future.
let RELOAD_PLUGINS_PROMISE_STARTED = false

export const reloadPlugins = async (hub: Hub): Promise<void> => {
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
        // No reload is in progress, schedule one. If multiple concurrent requests got in line
        // above, we only need one to schedule the reload here.

        RELOAD_PLUGINS_PROMISE = (async () => {
            // Jitter the reload time to avoid all workers reloading at the same time.
            const jitterMs = Math.random() * hub.RELOAD_PLUGIN_JITTER_MAX_MS
            logger.info('💤', `Sleeping for ${jitterMs}ms to jitter reloadPlugins`)
            await sleep(jitterMs)

            RELOAD_PLUGINS_PROMISE_STARTED = true
            try {
                const tries = 3
                const retrySleepMs = 5000
                await retryIfRetriable(async () => await setupPlugins(hub), tries, retrySleepMs)
            } finally {
                RELOAD_PLUGINS_PROMISE = undefined
                RELOAD_PLUGINS_PROMISE_STARTED = false
            }
        })()

        await RELOAD_PLUGINS_PROMISE
    }
}

// Does the initial plugins loading.
export async function initPlugins(hub: Hub): Promise<void> {
    ;['unhandledRejection', 'uncaughtException'].forEach((event) => {
        process.on(event, (error: Error) => {
            processUnhandledException(error, hub, event)
        })
    })
    await setupPlugins(hub)
}

export function processUnhandledException(error: Error, server: Hub, kind: string): void {
    let pluginConfig: PluginConfig | undefined = undefined

    if (error instanceof TimeoutError) {
        pluginConfig = error.pluginConfig
    } else {
        const pluginConfigId = pluginConfigIdFromStack(error.stack || '', server.pluginConfigSecretLookup)
        pluginConfig = pluginConfigId ? server.pluginConfigs.get(pluginConfigId) : undefined
    }

    if (pluginConfig) {
        void processError(server, pluginConfig, error)
        return
    }

    captureException(error, {
        extra: {
            type: `${kind} in worker`,
        },
    })

    logger.error('🤮', `${kind}!`, { error, stack: error.stack })
}

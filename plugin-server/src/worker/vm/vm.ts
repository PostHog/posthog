import { RetryError } from '@posthog/plugin-scaffold'
import { randomBytes } from 'crypto'
import { Summary } from 'prom-client'
import { VM } from 'vm2'

import { Hub, PluginConfig, PluginConfigVMResponse } from '../../types'
import { createCache } from './extensions/cache'
import { createConsole } from './extensions/console'
import { createPosthog } from './extensions/posthog'
import { createStorage } from './extensions/storage'
import { createUtils } from './extensions/utilities'
import { AVAILABLE_IMPORTS } from './imports'
import { transformCode } from './transforms'

export class TimeoutError extends RetryError {
    name = 'TimeoutError'
    caller?: string = undefined
    pluginConfig?: PluginConfig = undefined

    constructor(message: string, caller?: string, pluginConfig?: PluginConfig) {
        super(message)
        this.caller = caller
        this.pluginConfig = pluginConfig
    }
}

const vmSetupMsSummary = new Summary({
    name: 'vm_setup_ms',
    help: 'Time to setup vm',
    labelNames: ['plugin_id'],
})

export function createPluginConfigVM(
    hub: Hub,
    pluginConfig: PluginConfig, // NB! might have team_id = 0
    indexJs: string
): PluginConfigVMResponse {
    const timer = new Date()

    const usedImports: Set<string> = new Set()
    const transformedCode = transformCode(indexJs, hub, AVAILABLE_IMPORTS, usedImports)

    // Create virtual machine
    const vm = new VM({
        timeout: hub.TASK_TIMEOUT * 1000 + 1,
        sandbox: {},
    })

    // Add PostHog utilities to virtual machine
    vm.freeze(createConsole(hub, pluginConfig), 'console')
    vm.freeze(createPosthog(hub, pluginConfig), 'posthog')

    // Add non-PostHog utilities to virtual machine
    vm.freeze(AVAILABLE_IMPORTS['node-fetch'], 'fetch')

    // Add used imports to the virtual machine
    const pluginHostImports: Record<string, any> = {}
    for (const usedImport of usedImports) {
        pluginHostImports[usedImport] = (AVAILABLE_IMPORTS as Record<string, any>)[usedImport]
    }
    vm.freeze(pluginHostImports, '__pluginHostImports')

    if (process.env.NODE_ENV === 'test') {
        vm.freeze(setTimeout, '__jestSetTimeout')
    }

    vm.freeze(RetryError, 'RetryError')

    // Bring some useful globals into scope
    vm.freeze(URL, 'URL')

    // Creating this outside the vm (so not in a babel plugin for example)
    // because `setTimeout` is not available inside the vm... and we don't want to
    // make it available for now, as it makes it easier to create malicious code
    const asyncGuard = async (promise: Promise<any>, name?: string) => {
        const timeout = hub.TASK_TIMEOUT
        return await Promise.race([
            promise,
            new Promise((resolve, reject) =>
                setTimeout(() => {
                    const message = `Script execution timed out after promise waited for ${timeout} second${
                        timeout === 1 ? '' : 's'
                    } (${pluginConfig.plugin?.name}, name: ${name}, pluginConfigId: ${pluginConfig.id})`
                    reject(new TimeoutError(message, `${name}`, pluginConfig))
                }, timeout * 1000)
            ),
        ])
    }

    vm.freeze(asyncGuard, '__asyncGuard')

    vm.freeze(
        {
            cache: createCache(hub, pluginConfig.plugin_id, pluginConfig.team_id),
            config: pluginConfig.config,
            attachments: pluginConfig.attachments,
            storage: createStorage(hub, pluginConfig),
            utils: createUtils(hub, pluginConfig.id),
        },
        '__pluginHostMeta'
    )

    vm.run(`
        // two ways packages could export themselves (plus "global")
        const module = { exports: {} };
        let exports = {};

        // the plugin JS code
        ${transformedCode};
    `)

    // Add a secret hash to the end of some function names, so that we can (sometimes) identify
    // the crashed plugin if it throws an uncaught exception in a promise.
    if (!hub.pluginConfigSecrets.has(pluginConfig.id)) {
        const secret = randomBytes(16).toString('hex')
        hub.pluginConfigSecrets.set(pluginConfig.id, secret)
        hub.pluginConfigSecretLookup.set(secret, pluginConfig.id)
    }

    // Keep the format of this in sync with `pluginConfigIdFromStack` in utils.ts
    // Only place this after functions whose names match /^__[a-zA-Z0-9]+$/
    const pluginConfigIdentifier = `__PluginConfig_${pluginConfig.id}_${hub.pluginConfigSecrets.get(pluginConfig.id)}`
    const responseVar = `__pluginDetails${randomBytes(64).toString('hex')}`

    // Explicitly passing __asyncGuard to the returned function from `vm.run` in order
    // to make it harder to override the global `__asyncGuard = noop` inside plugins.
    // This way even if promises inside plugins are unbounded, the `processEvent` function
    // itself will still terminate after TASK_TIMEOUT seconds, not clogging the entire ingestion.
    vm.run(`
        if (typeof global.${responseVar} !== 'undefined') {
            throw new Error("Plugin created variable ${responseVar} that is reserved for the VM.")
        }
        let ${responseVar} = undefined;
        ((__asyncGuard) => {
            // where to find exports
            let exportDestinations = [
                exports,
                exports.default,
                module.exports
            ].filter(d => typeof d === 'object'); // filters out exports.default if not there

            // add "global" only if nothing exported at all
            if (!exportDestinations.find(d => Object.keys(d).length > 0)) {
                // we can't set it to just [global], as abstractions may add exports later
                exportDestinations.push(global)
            }

            // export helpers
            function __getExported (key) { return exportDestinations.find(a => a[key])?.[key] };
            function __asyncFunctionGuard (func, name) {
                return func ? function __innerAsyncGuard${pluginConfigIdentifier}(...args) { return __asyncGuard(func(...args), name) } : func
            };

            // inject the meta object + shareable 'global' to the end of each exported function
            const __pluginMeta = {
                ...__pluginHostMeta,
                global: {}
            };
            function __bindMeta (keyOrFunc) {
                const func = typeof keyOrFunc === 'function' ? keyOrFunc : __getExported(keyOrFunc);
                if (func) return function __inBindMeta${pluginConfigIdentifier} (...args) { return func(...args, __pluginMeta) };
            }
            function __callWithMeta (keyOrFunc, ...args) {
                const func = __bindMeta(keyOrFunc);
                if (func) return func(...args);
            }

            // we have processEventBatch, but not processEvent
            if (!__getExported('processEvent') && __getExported('processEventBatch')) {
                exports.processEvent = async function __processEvent${pluginConfigIdentifier} (event, meta) {
                    return (await (__getExported('processEventBatch'))([event], meta))?.[0]
                }
            }

            // export various functions
            const __methods = {
                setupPlugin: __asyncFunctionGuard(__bindMeta('setupPlugin'), 'setupPlugin'),
                teardownPlugin: __asyncFunctionGuard(__bindMeta('teardownPlugin'), 'teardownPlugin'),
                onEvent: __asyncFunctionGuard(__bindMeta('onEvent'), 'onEvent'),
                processEvent: __asyncFunctionGuard(__bindMeta('processEvent'), 'processEvent'),
                composeWebhook: __bindMeta('composeWebhook'),
                getSettings: __bindMeta('getSettings'),
            };

            ${responseVar} = { methods: __methods, meta: __pluginMeta, }
        })
    `)(asyncGuard)

    const vmResponse = vm.run(responseVar)
    const { methods } = vmResponse

    vmSetupMsSummary.labels(String(pluginConfig.plugin?.id)).observe(new Date().getTime() - timer.getTime())

    return {
        vm,
        methods,
        vmResponseVariable: responseVar,
        usedImports,
    }
}

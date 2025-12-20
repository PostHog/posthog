import { Hub, PluginsServerConfig } from '../types'

/**
 * Narrowed Hub type for the legacy plugin system.
 *
 * This type captures all the dependencies needed by the plugin VM,
 * plugin loading/teardown, and related functionality.
 */
export type LegacyPluginHub = Pick<
    PluginsServerConfig,
    | 'TASK_TIMEOUT'
    | 'RELOAD_PLUGIN_JITTER_MAX_MS'
    | 'PLUGIN_LOAD_SEQUENTIALLY'
    | 'BASE_DIR'
    | 'CDP_PLUGIN_CAPTURE_EVENTS_TOPIC'
> &
    Pick<
        Hub,
        | 'instanceId'
        | 'capabilities'
        | 'db'
        | 'kafkaProducer'
        | 'plugins'
        | 'pluginConfigs'
        | 'pluginConfigsPerTeam'
        | 'pluginConfigSecrets'
        | 'pluginConfigSecretLookup'
        | 'teamManager'
        | 'pluginsApiKeyManager'
        | 'celery'
    >

import { PluginConfigSchema } from 'posthog-plugins'

export function getConfigSchemaArray(
    configSchema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
): PluginConfigSchema[] {
    if (Array.isArray(configSchema)) {
        return configSchema
    } else {
        return Object.entries(configSchema)
            .map(([key, value]) => ({ key, ...value }))
            .sort((a, b) => (a.order || 999999) - (b.order || 999999))
    }
}

export function getConfigSchemaObject(
    configSchema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
): Record<string, PluginConfigSchema> {
    if (Array.isArray(configSchema)) {
        const newSchema: Record<string, PluginConfigSchema> = {}
        configSchema.forEach((conf, order) => {
            if (conf.key) {
                newSchema[conf.key] = { ...conf, order }
            }
        })
        return newSchema
    } else {
        return configSchema
    }
}

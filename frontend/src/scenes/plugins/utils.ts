import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

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

export function getPluginConfigFormData(
    editingPlugin: PluginTypeWithConfig,
    pluginConfigChanges: Record<string, any>
): FormData {
    const { __enabled: enabled, ...config } = pluginConfigChanges

    const configSchema = getConfigSchemaObject(editingPlugin.config_schema)

    const formData = new FormData()
    const otherConfig: Record<string, any> = {}
    formData.append('enabled', enabled)
    for (const [key, value] of Object.entries(config)) {
        if (configSchema[key]?.type === 'attachment') {
            if (value && !value.saved) {
                formData.append(`add_attachment[${key}]`, value)
            }
            if (!value && editingPlugin.pluginConfig.config[key]) {
                formData.append(`remove_attachment[${key}]`, 'true')
            }
        } else {
            otherConfig[key] = value
        }
    }
    formData.append('config', JSON.stringify(otherConfig))
    return formData
}

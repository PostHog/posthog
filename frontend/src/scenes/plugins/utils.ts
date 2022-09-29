import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import type { FormInstance } from 'antd/lib/form/hooks/useForm.d'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

// Keep this in sync with: posthog/api/plugin.py
export const SECRET_FIELD_VALUE = '**************** POSTHOG SECRET FIELD ****************'

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

export function defaultConfigForPlugin(plugin: PluginTypeWithConfig): Record<string, any> {
    const config: Record<string, any> = {}
    for (const field of getConfigSchemaArray(plugin.config_schema)) {
        if (field.key && typeof field.default !== 'undefined') {
            config[field.key] = field.default
        }
    }
    return config
}

export function getPluginConfigFormData(
    editingPlugin: PluginTypeWithConfig,
    pluginConfigChanges: Record<string, any>
): FormData {
    const { __enabled: enabled, ...config } = pluginConfigChanges

    const configSchema = getConfigSchemaObject(editingPlugin.config_schema)

    const formData = new FormData()
    const otherConfig: Record<string, any> = {}
    formData.append('enabled', Boolean(enabled).toString())
    for (const [key, value] of Object.entries(config)) {
        if (configSchema[key]?.type === 'attachment') {
            if (value && !value.saved) {
                formData.append(`add_attachment[${key}]`, value)
            }
            if (!value && editingPlugin.pluginConfig.config?.[key]) {
                formData.append(`remove_attachment[${key}]`, 'true')
            }
        } else if (!configSchema[key]?.secret || value !== SECRET_FIELD_VALUE) {
            // Omit the field from formData if it's a filled yet unchanged secret field
            otherConfig[key] = value
        }
    }
    formData.append('config', JSON.stringify(otherConfig))
    return formData
}

export const doFieldRequirementsMatch = (
    form: FormInstance<any>,
    targetFieldName: string | undefined,
    targetFieldValue: string | undefined
): boolean => {
    const formActualValue = form.getFieldValue(targetFieldName || '') || ''
    const targetAnyValue = typeof targetFieldValue === 'undefined'
    const formValueSet = !!formActualValue

    return (targetAnyValue && formValueSet) || targetFieldValue === formActualValue
}

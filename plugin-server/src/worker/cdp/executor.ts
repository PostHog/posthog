async function formatConfigTemplates(
    hub: Hub,
    pluginConfig: PluginConfig,
    event: PostIngestionEvent
): Promise<Record<string, any>> {
    const team = await hub.teamManager.fetchTeam(event.teamId)
    if (!team) {
        throw new Error('Team not found')
    }

    const schema = pluginConfig.plugin?.config_schema
    if (!schema) {
        // NOTE: This shouldn't be possible and is more about typings
        return pluginConfig.config
    }

    const schemaObject: Record<string, PluginConfigSchema> = Array.isArray(schema)
        ? Object.fromEntries(schema.map((field) => [field.key, field]))
        : schema

    const webhookFormatter = new MessageFormatter({
        event,
        team,
        siteUrl: hub.SITE_URL || 'http://localhost:8000',
        sourceName: pluginConfig.name || pluginConfig.plugin?.name || 'Unnamed plugin',
        sourcePath: `/pipeline/destinations/${pluginConfig.id}`,
    })

    const templatedConfig = { ...pluginConfig.config }

    Object.keys(templatedConfig).forEach((key) => {
        // If the field is a json field then we template it as such
        const { type, templating } = schemaObject[key] ?? {}
        const template = templatedConfig[key]

        if (type && templating) {
            if (type === 'string' && typeof template === 'string') {
                templatedConfig[key] = webhookFormatter.format(template)
            }

            if (type === 'json' && typeof template === 'string') {
                try {
                    templatedConfig[key] = JSON.stringify(webhookFormatter.formatJSON(JSON.parse(template)))
                } catch (error) {}
            }

            if (type === 'dictionary') {
                // TODO: Validate it really is a dictionary
                const dict: Record<string, string> = templatedConfig[key] as Record<string, string>
                const templatedDictionary: Record<string, string> = {}
                for (const [dictionaryKey, dictionaryValue] of Object.entries(dict)) {
                    templatedDictionary[dictionaryKey] = webhookFormatter.format(dictionaryValue)
                }
                templatedConfig[key] = templatedDictionary
            }
        }
    })

    return templatedConfig
}

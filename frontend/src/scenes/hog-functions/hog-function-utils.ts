import { CyclotronJobInputSchemaType, CyclotronJobInputType, HogFunctionType, HogFunctionTypeType } from '~/types'

export type HogFunctionDeliveryType = 'batch' | 'realtime'

// Batch exports vs realtime destinations share `type: 'destination'`; the only signal is the id prefix.
export function getHogFunctionDeliveryType(item: { id: string }): HogFunctionDeliveryType {
    return item.id.startsWith('batch-export-') ? 'batch' : 'realtime'
}

// A few inline plugins have a url slug that differs from their bundled processor id.
// Mirrors PLUGIN_ID_OVERRIDES in posthog/cdp/legacy_destination_migration.py.
const PLUGIN_ID_OVERRIDES: Record<string, string> = {
    'semver-flattener': 'semver-flattener-plugin',
    'user-agent': 'user-agent-plugin',
}

/** The bundled template a legacy plugin config runs, which a migrated legacy_destination also carries. */
export function legacyPluginTemplateId(pluginUrl: string | undefined): string | undefined {
    if (!pluginUrl) {
        return undefined
    }
    const pluginId = pluginUrl.replace('inline://', '').replace('https://github.com/PostHog/', '')
    return `plugin-${PLUGIN_ID_OVERRIDES[pluginId] ?? pluginId}`
}

/**
 * Drops a plugin config that a migrated legacy destination replaces, matching how the consumer picks
 * between them. Only an enabled migrated row supersedes: disable it and the plugin config runs again,
 * so it has to reappear rather than keep running out of sight.
 */
export function withoutSupersededPluginConfigs(
    hogFunctions: HogFunctionType[],
    manualFunctions: HogFunctionType[]
): HogFunctionType[] {
    const supersededTemplateIds = new Set(
        hogFunctions
            // The list serializer omits template_id and exposes the template's id instead
            .filter((f) => f.type === 'legacy_destination' && f.enabled)
            .map((f) => f.template_id ?? f.template?.id)
            .filter(Boolean)
    )
    return manualFunctions.filter((f) => !supersededTemplateIds.has(f.template_id))
}

export function humanizeHogFunctionType(type: HogFunctionTypeType, plural: boolean = false): string {
    if (type === 'source_webhook') {
        return 'source' + (plural ? 's' : '')
    }
    if (type === 'site_app') {
        return 'Web script' + (plural ? 's' : '')
    }
    if (type === 'transformation_log') {
        return 'log transformation' + (plural ? 's' : '')
    }
    return type.replaceAll('_', ' ') + (plural ? 's' : '')
}

/** Default char cap for a config blob attached to the PostHog AI agent as context. */
export const HOG_FUNCTION_CONTEXT_MAX_CHARS = 10_000

/**
 * Caps a stringified config blob before it's registered as PostHog AI attached context, so a pathological
 * hog source or inputs payload can't bloat the agent's context window. These are keyed entity-style items
 * (not `type: 'text'`), so they're sent once per run rather than every turn; the cap is a safety ceiling.
 */
export function truncateHogFunctionContext(value: string, max: number = HOG_FUNCTION_CONTEXT_MAX_CHARS): string {
    return value.length > max ? value.slice(0, max) + '… (truncated)' : value
}

/**
 * Replaces secret input values with a placeholder before the live form config leaves the scene (agent
 * context, approval-card diffs). A saved secret comes back masked from the API, but a value the user
 * just typed sits in form state in cleartext and must never reach the LLM. An entry counts as secret
 * when the schema marks its key secret or the entry itself carries `secret: true`.
 */
export function redactSecretHogFunctionInputs(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[]
): Record<string, CyclotronJobInputType> {
    const secretKeys = new Set(inputsSchema.filter((schema) => schema.secret).map((schema) => schema.key))
    return Object.fromEntries(
        Object.entries(inputs).map(([key, entry]) => {
            const isSecret = secretKeys.has(key) || entry?.secret === true
            return [key, isSecret && entry ? { ...entry, value: '[secret]' } : entry]
        })
    )
}

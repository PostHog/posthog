const CUSTOM_METADATA_MARKER = 'posthog_'
const RESERVED_CUSTOM_NAMES = new Set(['distinct_id'])

export function promotePosthogCustomMetadata(props: Record<string, unknown>, namespacePrefix: string): void {
    const prefix = `${namespacePrefix}${CUSTOM_METADATA_MARKER}`
    for (const key of Object.keys(props)) {
        if (!key.startsWith(prefix)) {
            continue
        }
        const name = key.slice(prefix.length)
        if (!name || name.startsWith('$') || RESERVED_CUSTOM_NAMES.has(name)) {
            continue
        }
        if (props[name] === undefined) {
            props[name] = props[key]
        }
    }
}

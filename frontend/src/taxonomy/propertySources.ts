import { PropertyKey } from './helpers'

export type ExternalPropertySourceId = 'langfuse' | 'expo'
export type PropertySourceId = 'posthog' | ExternalPropertySourceId

interface ExternalPropertySource {
    id: ExternalPropertySourceId
    /** Property keys starting with this were sent by this product. */
    prefix: string
    /** The page in the product's own app that the value points at, for the keys that identify something there. */
    valueUrl?: (key: string, value: string) => string | null
}

const EXPO_PAGE_BY_PROPERTY: Record<string, string> = {
    'eas/account': 'accounts',
    'eas/build_id': 'builds',
    'eas/project_id': 'projects',
    'eas/update_id': 'updates',
    'eas/workflow_id': 'workflows',
}

const EXTERNAL_PROPERTY_SOURCES: ExternalPropertySource[] = [
    { id: 'langfuse', prefix: 'langfuse ' },
    {
        id: 'expo',
        prefix: 'eas/',
        valueUrl: (key, value) => {
            const page = EXPO_PAGE_BY_PROPERTY[key]
            return page ? `https://expo.dev/${page}/${encodeURIComponent(value)}` : null
        },
    },
]

/** The product that sent a property, for keys that carry a recognized namespace. */
export function getExternalPropertySource(key: PropertyKey): ExternalPropertySource | null {
    const name = key?.toString() ?? ''
    return EXTERNAL_PROPERTY_SOURCES.find(({ prefix }) => name.startsWith(prefix)) ?? null
}

/** Where a property value opens in the product that sent it, so people can jump straight to it. */
export function getPropertyValueUrl(key: PropertyKey, value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null
    }
    const name = key?.toString() ?? ''
    return getExternalPropertySource(name)?.valueUrl?.(name, value.trim()) ?? null
}

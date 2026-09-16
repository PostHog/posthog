import { urls } from 'scenes/urls'

export interface EndpointModelName {
    endpointName: string
    version: number
}

// Matches EndpointVersion.saved_query_name. Endpoints depends on data modeling, not the reverse,
// so the name is the only link from a model back to its endpoint that this product can read.
const ENDPOINT_MODEL_NAME = /^(.+)_v(\d+)$/

export function parseEndpointModelName(name: string): EndpointModelName | null {
    const match = name.match(ENDPOINT_MODEL_NAME)
    return match ? { endpointName: match[1], version: parseInt(match[2], 10) } : null
}

export function endpointModelUrl(name: string): string {
    const parsed = parseEndpointModelName(name)
    return parsed ? urls.endpoint(parsed.endpointName, parsed.version) : urls.endpoint(name)
}

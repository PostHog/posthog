import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

export interface EndpointModelName {
    endpointName: string
    version: number
}

// Matches EndpointVersion.saved_query_name. Nodes enabled since the link was stamped carry it in
// `endpoint`; saved-query rows, schema tables and older nodes still have only the name to go on.
const ENDPOINT_MODEL_NAME = /^(.+)_v(\d+)$/

export function parseEndpointModelName(name: string): EndpointModelName | null {
    const match = name.match(ENDPOINT_MODEL_NAME)
    return match ? { endpointName: match[1], version: parseInt(match[2], 10) } : null
}

export function endpointModelUrl(name: string): string {
    const parsed = parseEndpointModelName(name)
    return parsed ? urls.endpoint(parsed.endpointName, parsed.version) : urls.endpoint(name)
}

type EndpointNodeLike = Pick<DataModelingNode, 'type' | 'name' | 'endpoint'>

export function nodeEndpointModel(node: EndpointNodeLike): EndpointModelName | null {
    if (node.type !== 'endpoint') {
        return null
    }
    if (node.endpoint) {
        return { endpointName: node.endpoint.name, version: node.endpoint.version }
    }
    return parseEndpointModelName(node.name)
}

export function nodeEndpointUrl(node: EndpointNodeLike): string {
    const model = nodeEndpointModel(node)
    return model ? urls.endpoint(model.endpointName, model.version) : urls.endpoint(node.name)
}

import type { EndpointsEndpointCreateInput } from '../generated/api.js'
import { type Definition, defineKind } from './definition.js'
import type { HogQLQueryNode } from './model.js'

export interface EndpointBody extends Omit<EndpointsEndpointCreateInput, 'name'> {
    name: string
}

export interface EndpointInput extends Omit<EndpointBody, 'name' | 'query'> {
    // `sql`, `file('./x.sql')`, or another query node.
    query: EndpointsEndpointCreateInput['query'] | HogQLQueryNode | string
}

export type EndpointDefinition<Name extends string = string> = Definition<'endpoint', Name, EndpointBody>

export function endpoint<const Name extends string>(name: Name, input: EndpointInput): EndpointDefinition<Name> {
    const { query, ...fields } = input
    const node = typeof query === 'string' ? { kind: 'HogQLQuery', query } : query
    return defineKind('endpoint', name, { ...fields, name, query: node as EndpointsEndpointCreateInput['query'] })
}

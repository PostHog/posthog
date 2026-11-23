import type { WarehouseSourcesExternalDataSourcesCreateInput } from '../generated/api.js'
import type { JsonValue } from '../types.js'
import { type Definition, defineKind, type SecretRef } from './definition.js'

export interface SourceInput extends Omit<WarehouseSourcesExternalDataSourcesCreateInput, 'payload'> {
    // Connection settings. Every credential is `secret('NAME')`: PostHog holds the value.
    payload: Readonly<Record<string, JsonValue | SecretRef>>
}

export type SourceDefinition<Key extends string = string> = Definition<'source', Key, SourceInput>

export function source<const Key extends string>(key: Key, body: SourceInput): SourceDefinition<Key> {
    return defineKind('source', key, body)
}

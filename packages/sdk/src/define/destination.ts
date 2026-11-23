import type { CdpFunctionsCdpFunctionsCreateInput } from '../generated/api.js'
import type { JsonValue } from '../types.js'
import { type Definition, defineKind, type Ref, type SecretRef } from './definition.js'

// JSON in which any value may also be a definition, a ref or a secret, as a destination's inputs
// and filters can name another entity, such as the alert whose firing it listens for.
export type DefinitionValue<T = JsonValue> = T extends readonly (infer Item)[]
    ? readonly DefinitionValue<Item>[]
    : T extends object
      ? { [Field in keyof T]: DefinitionValue<T[Field]> | undefined }
      : T | Definition | Ref | SecretRef

type Inputs = NonNullable<CdpFunctionsCdpFunctionsCreateInput['inputs']>
type Filters = NonNullable<CdpFunctionsCdpFunctionsCreateInput['filters']>

// A hog function: the create body, with references allowed inside its inputs and filters.
export interface DestinationInput extends Omit<CdpFunctionsCdpFunctionsCreateInput, 'inputs' | 'filters'> {
    inputs?: DefinitionValue<Inputs>
    filters?: DefinitionValue<Filters>
}

export type DestinationDefinition<Key extends string = string> = Definition<'destination', Key, DestinationInput>

export function destination<const Key extends string>(key: Key, body: DestinationInput): DestinationDefinition<Key> {
    return defineKind('destination', key, body)
}

import type { EventsEventDefinitionCreateInput } from '../generated/api.js'
import { type Definition, defineKind, type RefTo } from './definition.js'

// The property types of a schema property group, as the API names them.
export type PropertyType = 'String' | 'Numeric' | 'Boolean' | 'DateTime' | 'Object' | 'Array'

interface ValueOfType {
    String: string
    Numeric: number
    Boolean: boolean
    DateTime: string | Date
    Object: Record<string, unknown>
    Array: unknown[]
}

// One declared property. Each method returns a new spec, so a spec can be shared and refined.
export interface PropSpec<Value = unknown, Required extends boolean = boolean> {
    readonly property_type: PropertyType
    readonly is_required: Required
    readonly description?: string
    readonly enum?: readonly string[]
    // Only for the types: the TypeScript type a captured value has.
    readonly __value?: Value
    required(): PropSpec<Value, true>
    optional(): PropSpec<Value, false>
    describe(description: string): PropSpec<Value, Required>
}

function spec<Value>(
    property_type: PropertyType,
    fields: { is_required?: boolean; description?: string; enum?: readonly string[] } = {}
): PropSpec<Value, false> {
    const make = (next: typeof fields): PropSpec<Value, never> => {
        const value = {
            property_type,
            is_required: next.is_required ?? false,
            ...(next.description !== undefined ? { description: next.description } : {}),
            ...(next.enum !== undefined ? { enum: next.enum } : {}),
            required: () => make({ ...next, is_required: true }),
            optional: () => make({ ...next, is_required: false }),
            describe: (description: string) => make({ ...next, description }),
        }
        return Object.freeze(value) as unknown as PropSpec<Value, never>
    }
    return make(fields) as PropSpec<Value, false>
}

export const prop = {
    string: (): PropSpec<string, false> => spec<string>('String'),
    number: (): PropSpec<number, false> => spec<number>('Numeric'),
    boolean: (): PropSpec<boolean, false> => spec<boolean>('Boolean'),
    datetime: (): PropSpec<ValueOfType['DateTime'], false> => spec<ValueOfType['DateTime']>('DateTime'),
    object: (): PropSpec<object, false> => spec<object>('Object'),
    array: (): PropSpec<unknown[], false> => spec<unknown[]>('Array'),
    // A string property that takes one of these values. The API stores it as a String, and the
    // description keeps the members, for typed capture and generated modules.
    enum: <const Members extends readonly string[]>(members: Members): PropSpec<Members[number], false> =>
        spec<Members[number]>('String', { enum: members }),
}

export type PropSpecs = Readonly<Record<string, PropSpec>>

// A property reference inside `sql`: it renders as `properties.<name>`, quoted when it needs to be.
export const PROPERTY: unique symbol = Symbol.for('posthog.define.property')

export interface PropertyRef<Name extends string = string> {
    // `type` is the declared property type, so `sql` can read the value as that type.
    readonly [PROPERTY]: { event: string; name: Name; declared: boolean; type?: string }
}

export type PropertyRefs<Props extends PropSpecs> = { readonly [Name in keyof Props & string]: PropertyRef<Name> }

export interface PropertyGroupProperty {
    name: string
    property_type: PropertyType
    is_required?: boolean
    is_optional_in_types?: boolean
    description?: string
    // Not sent to PostHog, which has no field for it. Typed capture and generated modules read it.
    enum?: readonly string[]
}

// The schema property group create body. No generated type exists yet: the MCP tool for property
// groups is declared but not generated, so this follows the API serializer until it is.
export interface PropertyGroupBody {
    name: string
    description?: string
    properties: PropertyGroupProperty[]
}

export type PropertyGroupDefinition<Key extends string = string> = Definition<'property_group', Key, PropertyGroupBody>

export function propertyGroup<const Name extends string>(
    name: Name,
    body: Omit<PropertyGroupBody, 'name'>
): PropertyGroupDefinition<Name> {
    return defineKind('property_group', name, { name, ...body })
}

type EventData = NonNullable<EventsEventDefinitionCreateInput['data']>

export interface EventBody extends EventData {
    name: string
    property_groups?: readonly RefTo<'property_group'>[]
}

export interface EventInput<Props extends PropSpecs> extends Omit<EventBody, 'name' | 'property_groups'> {
    // `reject` drops events that don't match the declared properties.
    enforcement?: 'allow' | 'reject'
    properties?: Props
    // Further groups to link, besides the one `properties` makes.
    property_groups?: readonly RefTo<'property_group'>[]
}

export interface EventExtra<Props extends PropSpecs> {
    readonly properties: Props
    readonly props: PropertyRefs<Props>
}

export type EventDefinition<Name extends string = string, Props extends PropSpecs = PropSpecs> = Definition<
    'event',
    Name,
    EventBody
> &
    EventExtra<Props>

function propertyRefs<Props extends PropSpecs>(event: string, properties: Props): PropertyRefs<Props> {
    const declared = Object.fromEntries(
        Object.keys(properties).map((name) => [
            name,
            Object.freeze({
                [PROPERTY]: { event, name, declared: true, type: (properties[name] as PropSpec).property_type },
            }),
        ])
    )
    // JavaScript callers get no compile error for an undeclared name, so the reference records that
    // it is undeclared and `sql` reports it.
    return new Proxy(declared, {
        get: (target, name) =>
            typeof name === 'string' && !(name in target)
                ? { [PROPERTY]: { event, name, declared: false } }
                : target[name as string],
    }) as unknown as PropertyRefs<Props>
}

export function event<const Name extends string, const Props extends PropSpecs = {}>(
    name: Name,
    input: EventInput<Props> = {}
): EventDefinition<Name, Props> {
    const { enforcement, properties, property_groups = [], ...fields } = input
    const declared = (properties ?? {}) as Props
    const names = Object.keys(declared).sort()
    const group =
        names.length > 0
            ? propertyGroup(name, {
                  properties: names.map((property) => {
                      const { property_type, is_required, description, enum: members } = declared[property] as PropSpec
                      return {
                          name: property,
                          property_type,
                          is_required,
                          ...(description !== undefined ? { description } : {}),
                          ...(members !== undefined ? { enum: [...members] } : {}),
                      }
                  }),
              })
            : undefined
    const body: EventBody = {
        ...fields,
        name,
        ...(enforcement !== undefined ? { enforcement_mode: enforcement } : {}),
        ...(group || property_groups.length > 0
            ? { property_groups: [...(group ? [group] : []), ...property_groups] }
            : {}),
    }
    return defineKind('event', name, body, {}, { properties: declared, props: propertyRefs(name, declared) })
}

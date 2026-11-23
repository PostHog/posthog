import type { EventExtra, PropSpec, PropSpecs } from './event.js'
import type { FlagExtra } from './flag.js'

// Every value a stack module exports, one level into lists and records, as the stack walks them.
type Exported<Defs> = {
    [Name in keyof Defs]: Defs[Name] extends readonly (infer Item)[]
        ? Item
        : Defs[Name] extends { kind: string }
          ? Defs[Name]
          : Defs[Name] extends Record<string, infer Item>
            ? Item
            : never
}[keyof Defs]

type Events<Defs> = Extract<Exported<Defs>, { kind: 'event'; key: string } & EventExtra<PropSpecs>>
type Flags<Defs> = Extract<Exported<Defs>, { kind: 'flag'; key: string } & FlagExtra<string>>

export type EventNames<Defs> = Events<Defs>['key'] & string
export type FlagKeys<Defs> = Flags<Defs>['key'] & string

type ValueOfSpec<Spec> = Spec extends PropSpec<infer Value> ? Value : never
type RequiredNames<Props> = {
    [Name in keyof Props]: Props[Name] extends PropSpec<unknown, true> ? Name : never
}[keyof Props]

// Declared properties are typed, required ones required. Others may be sent too, as an event
// definition doesn't forbid them.
type CaptureProperties<Props> = { [Name in RequiredNames<Props>]: ValueOfSpec<Props[Name]> } & {
    [Name in Exclude<keyof Props, RequiredNames<Props>>]?: ValueOfSpec<Props[Name]>
} & Record<string, unknown>

type PropsOf<Defs, Name> = Extract<Events<Defs>, { key: Name }> extends EventExtra<infer Props> ? Props : never

export type PropertiesOf<Defs, Name extends EventNames<Defs>> = CaptureProperties<PropsOf<Defs, Name>>

export type VariantOf<Defs, Key extends FlagKeys<Defs>> =
    Extract<Flags<Defs>, { key: Key }> extends FlagExtra<infer Variant>
        ? [Variant] extends [never]
            ?
                  // Code owns a flag's variants only when its definition sets them, so a flag without
                  // them may still gain variants in PostHog.
                  boolean | string
            : Variant
        : never

// What `typed` needs from a client: posthog-js and posthog-react-native have both.
export interface CaptureClient {
    capture(event: string, properties?: Record<string, unknown> | null, options?: never): unknown
    getFeatureFlag(key: string): string | boolean | undefined | null
}

type OptionsOf<Client extends CaptureClient> = Client['capture'] extends (
    event: string,
    properties?: never,
    options?: infer Options
) => unknown
    ? Options
    : never

type ResultOf<Client extends CaptureClient> = ReturnType<Client['capture']>

type CaptureArguments<Defs, Name extends EventNames<Defs>, Options> = [RequiredNames<PropsOf<Defs, Name>>] extends [
    never,
]
    ? [properties?: PropertiesOf<Defs, Name>, options?: Options]
    : [properties: PropertiesOf<Defs, Name>, options?: Options]

export interface TypedMembers<Defs, Client extends CaptureClient> {
    // Only events the stack declares, with their declared properties.
    capture<Name extends EventNames<Defs>>(
        event: Name,
        ...args: CaptureArguments<Defs, Name, OptionsOf<Client>>
    ): ResultOf<Client>
    // The way out for an event that has no definition.
    captureRaw: Client['capture']
    // The variant this person gets, typed by the flag's declared variants. A flag whose definition sets no
    // variants gives a boolean, or a string if variants were added in PostHog.
    variant<Key extends FlagKeys<Defs>>(key: Key): VariantOf<Defs, Key> | undefined
}

// The client's own type, with `capture` narrowed and `captureRaw` and `variant` added.
export type TypedClient<Defs, Client extends CaptureClient = CaptureClient> = Omit<
    Client,
    keyof TypedMembers<Defs, Client>
> &
    TypedMembers<Defs, Client>

const OWN = new Set<PropertyKey>(['capture', 'captureRaw', 'variant'])

// Use with a type-only import, `import type * as defs from '../posthog'`, so nothing from the
// definitions reaches the bundle. Every other member reads and writes through to the client, so
// it behaves as the client does.
//
// `typed<typeof defs>()(client)` keeps the client's own type for its other members. TypeScript
// can't infer the client's type once the definitions' type is written out, so the one-call form
// `typed<typeof defs>(client)` types only what `CaptureClient` has.
export function typed<Defs>(): <Client extends CaptureClient>(client: Client) => TypedClient<Defs, Client>
export function typed<Defs, Client extends CaptureClient = CaptureClient>(client: Client): TypedClient<Defs, Client>
export function typed(client?: CaptureClient): unknown {
    return client === undefined ? wrap : wrap(client)
}

function wrap<Client extends CaptureClient>(client: Client): unknown {
    const capture = (event: string, properties?: Record<string, unknown> | null, options?: never): unknown =>
        client.capture(event, properties, options)
    const members = {
        capture,
        captureRaw: capture,
        variant: (key: string) => client.getFeatureFlag(key) ?? undefined,
    }
    return new Proxy(client, {
        get: (target, name, receiver) =>
            OWN.has(name) ? members[name as keyof typeof members] : Reflect.get(target, name, receiver),
    })
}

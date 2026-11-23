import type { FeatureFlagsCreateInput } from '../generated/api.js'
import type { JsonValue } from '../types.js'
import { type DefineIssue, type Definition, defineKind, withIssues } from './definition.js'

export interface FlagBody extends Omit<FeatureFlagsCreateInput, 'key'> {
    key: string
}

type Filters = NonNullable<FeatureFlagsCreateInput['filters']>

type ApiVariant = NonNullable<NonNullable<Filters['multivariate']>['variants']>[number]

export interface FlagVariant<Variant extends string = string> extends Omit<ApiVariant, 'key'> {
    key: Variant
}

// Code owns a flag's variants and payloads when the definition sets them, so they are set here and
// never through `filters`, and `typed().variant()` knows every variant the flag can return. The
// release conditions, `filters.groups`, are only where the flag starts: PostHog owns them after
// the flag is created.
export interface FlagInput<Variant extends string> extends Omit<FlagBody, 'key' | 'filters'> {
    // Variant keys and their rollout percentages, the keys alone for an even split, or the
    // variants as the API has them.
    variants?: Readonly<Record<Variant, number>> | readonly Variant[] | readonly FlagVariant<Variant>[]
    // Payloads by variant key, or under `true` for a flag without variants. A value that isn't a
    // string is sent as its JSON text, as the API stores it.
    payloads?: Readonly<Partial<Record<[Variant] extends [never] ? 'true' : Variant, JsonValue>>>
    // One release condition for everyone, at this percentage.
    rollout?: number
    // `multivariate: null` is how the API says a flag has no variants.
    filters?: Omit<Filters, 'multivariate' | 'payloads'> & { multivariate?: null }
}

export interface FlagExtra<Variant extends string> {
    // Only for the types: the variants `typed().variant()` returns.
    readonly variants: readonly Variant[]
}

export type FlagDefinition<Key extends string = string, Variant extends string = string> = Definition<
    'flag',
    Key,
    FlagBody
> &
    FlagExtra<Variant>

function evenSplit(keys: readonly string[]): { key: string; rollout_percentage: number }[] {
    const share = Math.floor(100 / keys.length)
    return keys.map((key, index) => ({
        key,
        rollout_percentage: index === keys.length - 1 ? 100 - share * (keys.length - 1) : share,
    }))
}

export function flag<const Key extends string, const Variant extends string = never>(
    key: Key,
    input: FlagInput<Variant> = {}
): FlagDefinition<Key, Variant> {
    const { variants, payloads, rollout, filters, ...fields } = input
    const variantList: FlagVariant[] | undefined =
        variants === undefined
            ? undefined
            : Array.isArray(variants)
              ? variants.every((variant) => typeof variant === 'string')
                  ? evenSplit(variants as readonly string[])
                  : (variants as readonly FlagVariant[]).map((variant) => ({ ...variant }))
              : Object.entries(variants as Record<string, number>).map(([variant, rollout_percentage]) => ({
                    key: variant,
                    rollout_percentage,
                }))
    // JavaScript callers can still pass these; each is set one way only, so nothing is merged.
    const given = (filters ?? {}) as Filters
    const issues: DefineIssue[] = [
        ...(given.multivariate !== undefined && given.multivariate !== null
            ? [
                  {
                      code: 'flag_field_moved',
                      path: 'filters.multivariate',
                      message:
                          'Set the variants with the variants option, not filters.multivariate, so typed().variant() knows them.',
                  },
              ]
            : []),
        ...(given.payloads !== undefined
            ? [
                  {
                      code: 'flag_field_moved',
                      path: 'filters.payloads',
                      message: 'Set the payloads with the payloads option, not filters.payloads.',
                  },
              ]
            : []),
        ...(rollout !== undefined && given.groups !== undefined
            ? [
                  {
                      code: 'flag_field_moved',
                      path: 'filters.groups',
                      message: 'Set the release conditions with rollout or with filters.groups, not both.',
                  },
              ]
            : []),
    ]
    const merged: Filters = {
        ...filters,
        ...(rollout !== undefined ? { groups: [{ properties: [], rollout_percentage: rollout }] } : {}),
        ...(variantList ? { multivariate: { variants: variantList } } : {}),
        ...(payloads
            ? {
                  payloads: Object.fromEntries(
                      Object.entries(payloads).map(([variant, value]) => [
                          variant,
                          typeof value === 'string' ? value : JSON.stringify(value),
                      ])
                  ),
              }
            : {}),
    }
    const body: FlagBody = {
        ...fields,
        key,
        ...(filters !== undefined || Object.keys(merged).length > 0 ? { filters: merged } : {}),
    }
    return defineKind(
        'flag',
        key,
        withIssues(body, issues),
        {},
        { variants: (variantList ?? []).map((variant) => variant.key) as Variant[] }
    )
}

import { LemonSelect, LemonSelectProps, LemonSelectPropsClearable, LemonSelectPropsNonClearable } from './LemonSelect'

export type LemonSearchableSelectPropsClearable<T> = LemonSelectPropsClearable<T>

export type LemonSearchableSelectPropsNonClearable<T> = LemonSelectPropsNonClearable<T>

export type LemonSearchableSelectProps<T> = LemonSelectProps<T>

/**
 * A `LemonSelect` with the dropdown search always on.
 *
 * `LemonSelect` now has search built in (enabled automatically for long option lists), so prefer it directly —
 * this wrapper only forces `searchable` for callers that want search regardless of option count.
 */
export function LemonSearchableSelect<T extends string | number | boolean | null>(
    props: LemonSearchableSelectProps<T>
): JSX.Element {
    // Cast to `any` because LemonSelectProps is a union (clearable vs non-clearable) and TS can't spread it as JSX props.
    return <LemonSelect {...(props as any)} searchable />
}

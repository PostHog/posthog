import type { LegendValue } from '@posthog/quill-charts'

export const CALCS = ['mean', 'max', 'min', 'last', 'sum', 'delta'] as const satisfies readonly LegendValue[]
export type Calc = (typeof CALCS)[number]

export function legendClick(hidden: Set<string>, keys: string[], key: string, additive: boolean): Set<string> {
    if (additive) {
        const n = new Set(hidden)
        n.has(key) ? n.delete(key) : n.add(key)
        return n
    }
    const others = keys.filter((k) => k !== key)
    return !hidden.has(key) && others.every((k) => hidden.has(k)) ? new Set() : new Set(others)
}

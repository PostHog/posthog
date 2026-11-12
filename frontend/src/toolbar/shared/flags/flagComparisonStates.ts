import type { FlagInfo } from './flagInfo'

export interface ComparisonState {
    value: string | boolean
    label: string
}

/** Off comes first, so it is the "before" image. Then on, or each variant of a multivariate flag. */
export function comparisonStates(flag: FlagInfo): ComparisonState[] {
    const off: ComparisonState = { value: false, label: 'Off' }
    if (flag.variants.length === 0) {
        return [off, { value: true, label: 'On' }]
    }
    return [off, ...flag.variants.map((variant) => ({ value: variant.key, label: variant.key }))]
}

/** The capture the diff shows as "after": the variant the user picked, or else the first capture with the flag on. */
export function pickAfterCapture<Capture extends ComparisonState>(
    onCaptures: Capture[],
    afterValue: string | boolean | null
): Capture | null {
    return onCaptures.find((capture) => capture.value === afterValue) ?? onCaptures[0] ?? null
}

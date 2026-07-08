import { LemonSelectSection } from 'lib/lemon-ui/LemonSelect/LemonSelect'

import { FunnelsAlertConfig } from '~/queries/schema/schema-general'

/** Single-dropdown funnel conversion picker.
 *
 * The `{metric, funnel_step}` data model can express invalid combinations (e.g. `conversion_from_previous`
 * at step 1, which has no prior step). Rather than expose two coupled dropdowns whose cartesian product
 * includes nonsense, we enumerate only the valid conversions as labeled options keyed by a stable string,
 * then map back to the config on selection. Each key encodes the underlying `{metric, funnel_step}`:
 *
 *   - `overall`   → whole-funnel conversion (first step → last step)        {conversion_from_start, null}
 *   - `prev:<i>`  → step-over-step conversion into step i (1-based index)   {conversion_from_previous, i}
 *   - `start:<i>` → cumulative conversion from entry to step i              {conversion_from_start, i}
 *
 * Two groups: "Step-over-step" (every adjacent transition) and "From entry" (cumulative reach from the
 * first step). `start:1` is omitted because it equals `prev:1` (both are step1/step0) — it's covered by
 * the step-over-step group. The overall conversion is the final, full-funnel member of the From-entry
 * group (rather than its own section), so that group always reads as a complete set.
 */

const OVERALL = 'overall'

export function funnelConversionOptions(stepLabels: string[]): LemonSelectSection<string>[] {
    const n = stepLabels.length
    if (n < 2) {
        return []
    }
    const first = stepLabels[0]
    const last = stepLabels[n - 1]

    // A 2-step funnel has exactly one conversion; `prev:1` would just duplicate the overall rate.
    if (n === 2) {
        return [{ options: [{ label: `${first} → ${last}`, value: OVERALL }] }]
    }

    // Cumulative reach from entry to each intermediate step (step 1 is the first step-over-step), then
    // the overall conversion as the full-funnel member so the group reads as a complete set.
    const fromEntry = []
    for (let step = 2; step <= n - 2; step++) {
        fromEntry.push({ label: `${first} → ${stepLabels[step]}`, value: `start:${step}` })
    }
    // first → last is self-evidently the whole-funnel conversion, so it needs no "overall" label.
    fromEntry.push({ label: `${first} → ${last}`, value: OVERALL })

    return [
        {
            title: 'Step-over-step',
            options: Array.from({ length: n - 1 }, (_, k) => {
                const step = k + 1
                return { label: `${stepLabels[step - 1]} → ${stepLabels[step]}`, value: `prev:${step}` }
            }),
        },
        { title: 'From entry', options: fromEntry },
    ]
}

/** Resolve the current config to the option key whose rate it computes, normalizing the equivalences
 * above (null step = last step; `from_start` at step 1 = `prev:1`) so the dropdown always has a selection. */
export function funnelConfigToOptionKey(config: FunnelsAlertConfig, stepCount: number): string {
    const last = stepCount - 1
    const index = config.funnel_step ?? last

    if (config.metric === 'conversion_from_previous') {
        // Step 1 (or below) is undefined for from-previous; fall back to overall rather than leave it blank.
        return index <= 0 || stepCount === 2 ? OVERALL : `prev:${index}`
    }
    // conversion_from_start
    if (index >= last) {
        return OVERALL
    }
    if (index <= 1) {
        return stepCount === 2 ? OVERALL : 'prev:1'
    }
    return `start:${index}`
}

/** Map a selected option key back to the config fields it sets. */
export function funnelConfigForOptionKey(key: string): Pick<FunnelsAlertConfig, 'metric' | 'funnel_step'> {
    if (key === OVERALL) {
        return { metric: 'conversion_from_start', funnel_step: null }
    }
    const [kind, indexStr] = key.split(':')
    const index = Number(indexStr)
    return kind === 'prev'
        ? { metric: 'conversion_from_previous', funnel_step: index }
        : { metric: 'conversion_from_start', funnel_step: index }
}

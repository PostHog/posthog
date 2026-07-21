import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils/objects'
import { pluralize } from 'lib/utils/strings'
import { BREAKDOWN_BASELINE_STRING_LABEL } from 'scenes/insights/utils'

import {
    BreakdownItem,
    FunnelsActorsQuery,
    InsightActorsQuery,
    InsightActorsQueryOptionsResponse,
    insightActorsQueryOptionsResponseKeys,
} from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { StepOrderValue } from '~/types'

export const funnelTitle = (props: {
    converted: boolean
    step: number
    breakdown_value?: string
    label?: string
    seriesId?: number
    order_type?: StepOrderValue
}): JSX.Element => {
    return (
        <>
            {props.order_type === StepOrderValue.UNORDERED ? (
                <>
                    {props.converted ? (
                        <>Completed {pluralize(props.step, 'step', 'steps')}</>
                    ) : (
                        <>
                            Completed {pluralize(props.step - 1, 'step', 'steps')}, did not complete{' '}
                            {pluralize(props.step, 'step', 'steps')}
                        </>
                    )}
                </>
            ) : (
                <>
                    {props.converted ? 'Completed' : 'Dropped off at'} step {props.step} •{' '}
                    <PropertyKeyInfo value={props.label || ''} disablePopover type={TaxonomicFilterGroupType.Events} />
                </>
            )}{' '}
            {props?.breakdown_value ? `• ${props.breakdown_value}` : ''}
        </>
    )
}

type pathModes = 'completion' | 'dropOff' | 'continue'
export const pathsTitle = (props: { mode: pathModes; label: string }): React.ReactNode => {
    const modeMap: Record<pathModes, string> = {
        completion: 'Completed',
        dropOff: 'Dropped off after',
        continue: 'Continued after',
    }
    return (
        <>
            {modeMap[props.mode]} step{' '}
            <PropertyKeyInfo value={props.label.replace(/(^[0-9]+_)/, '') || ''} disablePopover />
        </>
    )
}

// `InsightActorsQueryOptionsResponse` also carries non-option fields (e.g. `warnings` inherited
// from analytics-response semantics) that must not be rendered as UI option lists. Exclude them
// from the option-key union, and iterate the explicit allowlist at runtime rather than Object.keys.
type InsightActorsQueryOptionKey = Exclude<keyof InsightActorsQueryOptionsResponse, 'warnings'>
type InsightActorsQueryOptionTuple = {
    [K in InsightActorsQueryOptionKey]: [K, NonNullable<InsightActorsQueryOptionsResponse[K]>]
}[InsightActorsQueryOptionKey]

/** Backend option values are `string | number`, so array breakdown values arrive JSON-encoded. */
const parseFunnelBreakdownOptionValue = (value: string | number): string | number | (string | number)[] => {
    if (typeof value === 'string' && value.startsWith('[')) {
        try {
            const parsed = JSON.parse(value)
            if (Array.isArray(parsed)) {
                return parsed
            }
        } catch {
            // a literal breakdown value that merely looks like JSON
        }
    }
    return value
}

/** Map a breakdown dropdown selection back onto `funnelStepBreakdown` (Baseline = no filter). */
export const funnelStepBreakdownFromSelectValue = (
    value: string | number | null
): FunnelsActorsQuery['funnelStepBreakdown'] => {
    if (value === null || value === BREAKDOWN_BASELINE_STRING_LABEL) {
        return null
    }
    return parseFunnelBreakdownOptionValue(value)
}

/**
 * Find the dropdown option matching the query's current `funnelStepBreakdown`. Matches by parsed
 * deep-compare rather than re-serializing in JS, so nothing depends on byte-identical JSON between
 * Python and JS. Returns null (no selection) when the current value isn't among the options.
 */
export const funnelBreakdownSelectValue = (
    funnelStepBreakdown: FunnelsActorsQuery['funnelStepBreakdown'],
    options: BreakdownItem[]
): string | number | null => {
    if (funnelStepBreakdown === null || funnelStepBreakdown === undefined) {
        return BREAKDOWN_BASELINE_STRING_LABEL
    }
    const current =
        Array.isArray(funnelStepBreakdown) && funnelStepBreakdown.length === 1
            ? funnelStepBreakdown[0]
            : funnelStepBreakdown
    const match = options.find((option) => {
        const optionValue = parseFunnelBreakdownOptionValue(option.value)
        if (objectsEqual(optionValue, current)) {
            return true
        }
        // Tolerate numeric/string drift between result values and option values.
        return !Array.isArray(current) && !Array.isArray(optionValue) && String(optionValue) === String(current)
    })
    return match ? match.value : null
}

export const cleanedInsightActorsQueryOptions = (
    insightActorsQueryOptions: InsightActorsQueryOptionsResponse | null,
    query: InsightActorsQuery | FunnelsActorsQuery
): InsightActorsQueryOptionTuple[] => {
    const cleanedOptions: InsightActorsQueryOptionTuple[] = []
    for (const key of insightActorsQueryOptionsResponseKeys as InsightActorsQueryOptionKey[]) {
        const value = insightActorsQueryOptions?.[key]
        if (Array.isArray(value) && value.length > 0) {
            cleanedOptions.push([key, value] as InsightActorsQueryOptionTuple)
        }
    }

    const source = query?.source
    const seriesNames = isTrendsQuery(source) ? source.series.map((s: any) => s.custom_name) : []

    const transformed: InsightActorsQueryOptionTuple[] = []
    for (const option of cleanedOptions) {
        const [key, value] = option
        if (key === 'series') {
            transformed.push([
                'series',
                value.map((v, index) => ({
                    ...v,
                    label:
                        seriesNames[index] ??
                        getCoreFilterDefinition(v.label, TaxonomicFilterGroupType.Events)?.label ??
                        v.label,
                })),
            ])
            continue
        }
        transformed.push(option)
    }

    return transformed
}

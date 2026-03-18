import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { pluralize } from 'lib/utils'

import { InsightActorsQuery, InsightActorsQueryOptionsResponse } from '~/queries/schema/schema-general'
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

type InsightActorsQueryOptionKey = keyof InsightActorsQueryOptionsResponse
type InsightActorsQueryOptionTuple = {
    [K in InsightActorsQueryOptionKey]: [K, NonNullable<InsightActorsQueryOptionsResponse[K]>]
}[InsightActorsQueryOptionKey]

export const cleanedInsightActorsQueryOptions = (
    insightActorsQueryOptions: InsightActorsQueryOptionsResponse | null,
    query: InsightActorsQuery
): InsightActorsQueryOptionTuple[] => {
    const cleanedOptions: InsightActorsQueryOptionTuple[] = []
    for (const key of Object.keys(insightActorsQueryOptions ?? {}) as InsightActorsQueryOptionKey[]) {
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

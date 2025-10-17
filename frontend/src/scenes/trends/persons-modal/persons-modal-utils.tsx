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

export const cleanedInsightActorsQueryOptions = (
    insightActorsQueryOptions: InsightActorsQueryOptionsResponse | null,
    query: InsightActorsQuery
): [string, any[]][] => {
    const cleanedOptions = Object.entries(insightActorsQueryOptions ?? {}).filter(([, value]) => {
        return Array.isArray(value) && !!value.length
    })
    const source = query?.source
    const seriesNames = isTrendsQuery(source) ? source.series.map((s: any) => s.custom_name) : []
    const cleanedOptionsWithAdjustedSeriesNames: [string, any[]][] = cleanedOptions.map(([key, value]) => {
        if (key === 'series') {
            return [
                key,
                value.map((v: any, index: number) => ({
                    ...v,
                    label:
                        seriesNames[index] ??
                        getCoreFilterDefinition(v.label, TaxonomicFilterGroupType.Events)?.label ??
                        v.label,
                })),
            ]
        }
        return [key, value]
    })

    return cleanedOptionsWithAdjustedSeriesNames
}

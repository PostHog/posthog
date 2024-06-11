import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { pluralize } from 'lib/utils'

import { InsightActorsQueryOptionsResponse } from '~/queries/schema'
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
                        <>Completed {pluralize(props.step, 'step', 'steps')} </>
                    ) : (
                        <>
                            Completed {pluralize(props.step - 1, 'step', 'steps')}, did not complete{' '}
                            {pluralize(props.step, 'step', 'steps')}{' '}
                        </>
                    )}
                </>
            ) : (
                <>
                    {props.converted ? 'Completed' : 'Dropped off at'} step {props.step} •{' '}
                    <PropertyKeyInfo value={props.label || ''} disablePopover type={TaxonomicFilterGroupType.Events} />{' '}
                </>
            )}
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
    insightActorsQueryOptions: InsightActorsQueryOptionsResponse | null
): [string, any[]][] => {
    return Object.entries(insightActorsQueryOptions ?? {}).filter(([, value]) => {
        return Array.isArray(value) && !!value.length
    })
}

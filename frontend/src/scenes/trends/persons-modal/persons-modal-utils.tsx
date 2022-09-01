import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { dayjs } from 'lib/dayjs'
import { convertPropertiesToPropertyGroup, toParams } from 'lib/utils'
import React from 'react'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import {
    ActionFilter,
    ChartDisplayType,
    FilterLogicalOperator,
    FilterType,
    FunnelVizType,
    GraphDataset,
    InsightType,
} from '~/types'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'

export const funnelTitle = (props: {
    step: number
    breakdown_value?: string
    label?: string
    seriesId?: number
}): JSX.Element => {
    return (
        <>
            {(props.step ?? 0) >= 0 ? 'Completed' : 'Dropped off at'} step {Math.abs(props?.step ?? 0)} •{' '}
            <PropertyKeyInfo value={props.label || ''} disablePopover />{' '}
            {!!props?.breakdown_value ? `• ${props.breakdown_value}` : ''}
        </>
    )
}

export const pathsTitle = (props: { isDropOff: boolean; label: string }): React.ReactNode => {
    return (
        <>
            {props.isDropOff ? 'Dropped off after' : 'Completed'} step{' '}
            <PropertyKeyInfo value={props.label.replace(/(^[0-9]+_)/, '') || ''} disablePopover />
        </>
    )
}

export const urlsForDatasets = (
    crossDataset: GraphDataset[] | undefined,
    index: number
): { value: string; label: JSX.Element }[] => {
    const showCountedByTag = !!crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    const hasMultipleSeries = !!crossDataset?.find(({ action }) => action?.order)

    if (crossDataset?.length === 1 && crossDataset[0].actions) {
        const dataset = crossDataset[0]
        return (
            dataset.actions?.map((action, i) => ({
                value: dataset?.personsValues?.[i]?.url || '',
                label: (
                    <InsightLabel
                        seriesColor={getSeriesColor(action.order)}
                        action={action}
                        breakdownValue={
                            dataset.breakdownValues?.[i] === '' ? 'None' : dataset.breakdownValues?.[i]?.toString()
                        }
                        showCountedByTag={showCountedByTag}
                        hasMultipleSeries={hasMultipleSeries}
                    />
                ),
            })) || []
        )
    }

    return (
        crossDataset
            ?.map((dataset) => ({
                value: dataset.persons_urls?.[index].url || dataset.personsValues?.[index]?.url || '',
                label: (
                    <>
                        <InsightLabel
                            seriesColor={getSeriesColor(dataset.id)}
                            action={dataset.action}
                            breakdownValue={
                                dataset.breakdown_value === '' ? 'None' : dataset.breakdown_value?.toString()
                            }
                            showCountedByTag={showCountedByTag}
                            hasMultipleSeries={hasMultipleSeries}
                        />
                        {/* {dataset.action.status} */}
                    </>
                ),
            }))
            .filter((x) => x.value) || []
    )
}

export interface PeopleParamType {
    action?: ActionFilter
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
}

export interface PeopleUrlBuilderParams extends PeopleParamType {
    filters: Partial<FilterType>
    funnelStep?: number
}

export function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterTrendsClientSideParams({
        ...filters,
        entity_id: action?.id || filters?.events?.[0]?.id || filters?.actions?.[0]?.id,
        entity_type: action?.type || filters?.events?.[0]?.type || filters?.actions?.[0]?.type,
        entity_math: action?.math || undefined,
        breakdown_value,
    })

    // casting here is not the best
    if (filters.insight === InsightType.STICKINESS) {
        params.stickiness_days = date_from as number
    } else if (params.display === ChartDisplayType.ActionsLineGraphCumulative) {
        params.date_to = date_from as string
    } else if (filters.insight === InsightType.LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = date_from as string
        params.date_to = date_to as string
    }

    // Ensure properties are property groups
    params.properties = convertPropertiesToPropertyGroup(params.properties)

    // Merge action property group
    if (action?.properties?.values && (action.properties.values?.length ?? 0) > 0) {
        params.properties = {
            type: FilterLogicalOperator.And,
            values: [params.properties, convertPropertiesToPropertyGroup(action.properties)],
        }
    }

    return toParams({ ...params, ...restParams })
}

// NOTE: Ideally this should be built server side and returned in `persons_urls` but for those that don't support it we can built it on the frontend
export const buildPeopleUrl = ({
    label,
    action,
    filters,
    date_from,
    date_to,
    breakdown_value,
    funnelStep,
}: PeopleUrlBuilderParams): string | undefined => {
    if (filters.funnel_correlation_person_entity) {
        const cleanedParams = cleanFilters(filters)
        return `api/person/funnel/correlation/?${cleanedParams}`
    } else if (filters.insight === InsightType.LIFECYCLE) {
        const filterParams = parsePeopleParams(
            { label, action, target_date: date_from, lifecycle_type: breakdown_value },
            filters
        )
        return `api/person/lifecycle/?${filterParams}`
    } else if (filters.insight === InsightType.STICKINESS) {
        const filterParams = parsePeopleParams({ label, action, date_from, date_to, breakdown_value }, filters)
        return `api/person/stickiness/?${filterParams}`
    } else if (funnelStep || filters.funnel_viz_type === FunnelVizType.Trends) {
        let params
        if (filters.funnel_viz_type === FunnelVizType.Trends) {
            // funnel trends
            const entrance_period_start = dayjs(date_from).format('YYYY-MM-DD HH:mm:ss')
            params = { ...filters, entrance_period_start, drop_off: false }
        } else {
            // regular funnel steps
            params = {
                ...filters,
                funnel_step: funnelStep,
                ...(breakdown_value !== undefined && { funnel_step_breakdown: breakdown_value }),
            }
        }
        const cleanedParams = cleanFilters(params)
        const funnelParams = toParams(cleanedParams)
        return `api/person/funnel/?${funnelParams}`
    } else if (filters.insight === InsightType.PATHS) {
        const cleanedParams = cleanFilters(filters)
        const pathParams = toParams(cleanedParams)

        console.log({ pathParams, filters })

        return `api/person/path/?${pathParams}`
    } else {
        return `api/projects/@current/actions/people?${parsePeopleParams(
            { label, action, date_from, date_to, breakdown_value },
            filters
        )}`
    }
}

import * as Sentry from '@sentry/react'
import { getBarColorFromStatus, getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, pluralize, toParams } from 'lib/utils'
import md5 from 'md5'
import { isFunnelsFilter, isPathsFilter } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

import {
    FunnelsFilterType,
    FunnelVizType,
    GraphDataset,
    LifecycleToggle,
    PathsFilterType,
    StepOrderValue,
} from '~/types'

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
                    <PropertyKeyInfo value={props.label || ''} disablePopover />{' '}
                </>
            )}
            {props?.breakdown_value ? `• ${props.breakdown_value}` : ''}
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
                        seriesColor={dataset?.backgroundColor?.[i] || getSeriesColor(action.order)}
                        action={action}
                        breakdownValue={
                            dataset.breakdownValues?.[i] === '' ? 'None' : dataset.breakdownValues?.[i]?.toString()
                        }
                        showCountedByTag={showCountedByTag}
                        hasMultipleSeries={hasMultipleSeries}
                        showEventName
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
                    <InsightLabel
                        seriesColor={
                            dataset.status
                                ? getBarColorFromStatus(dataset.status as LifecycleToggle)
                                : getSeriesColor(dataset.id)
                        }
                        action={dataset.action}
                        breakdownValue={
                            dataset.status
                                ? capitalizeFirstLetter(dataset.status)
                                : dataset.breakdown_value === ''
                                ? 'None'
                                : dataset.breakdown_value?.toString()
                        }
                        showCountedByTag={showCountedByTag}
                        hasMultipleSeries={hasMultipleSeries}
                        showEventName
                    />
                ),
            }))
            .filter((x) => x.value) || []
    )
}

interface PeopleUrlBuilderParams {
    filters: Partial<FunnelsFilterType> | Partial<PathsFilterType>
    date_from?: string | number
    funnelStep?: number
    /** We use values from the reponse, in addition to filters, to derive a cached invalidation key. */
    response?: Record<string, any> | null
}

/**
 * **This function is used to derive a somewhat stable key that still invalidates
 * person endpoint results when an insight was refreshed.**
 *
 * Some of our person endpoints use the @cached_function decorator for response
 * caching. This cache can be invalidated by sending a differing
 * `cache_invalidation_key`.
 *
 * Usually this key is generated for the person urls in an insight response
 * on the backend. This results in fresh person responses for a refreshed
 * insight. The key itself is just a random string.
 *
 * For insights where we build the person url on the frontend and the person
 * endpoint is cached using the mentioned decorator, we need to generate the
 * key on the frontend.
 */
const deriveCacheInvalidationKey = ({ filters, date_from, funnelStep, response }: PeopleUrlBuilderParams): string => {
    if (!response || !response['last_refresh']) {
        // we should never land here, invalidate always
        return `fe_${Date.now().toString()}_invalidate_always`
    }
    const payload = JSON.stringify({ ...filters, date_from, funnelStep, lastRefresh: response['last_refresh'] })
    // "fe_" for signaling this is a frontend side generated cache invalidation key
    return `fe_${md5(payload).slice(0, 8)}`
}

// NOTE: Ideally this should be built server side and returned in `persons_urls` but for those that don't support it we can built it on the frontend
export const buildPeopleUrl = ({
    filters,
    date_from,
    funnelStep,
    response,
}: PeopleUrlBuilderParams): string | undefined => {
    const cacheInvalidationKey = deriveCacheInvalidationKey({ filters, date_from, funnelStep, response })
    if (isFunnelsFilter(filters) && filters.funnel_correlation_person_entity) {
        // TODO: We should never land in this case; Remove this if Sentry doesn't unexpectedly capture this.
        Sentry.captureException(new Error('buildPeopleUrl used for funnel correlation'), {
            extra: { filters },
        })
    } else if (isFunnelsFilter(filters) && (funnelStep || filters.funnel_viz_type === FunnelVizType.Trends)) {
        let params
        if (filters.funnel_viz_type === FunnelVizType.Trends) {
            // funnel trends
            const entrance_period_start = dayjs(date_from).format('YYYY-MM-DD HH:mm:ss')
            params = { ...filters, entrance_period_start, drop_off: false }
            const cleanedParams = cleanFilters(params)
            const funnelParams = toParams(cleanedParams)
            return `api/person/funnel/?${funnelParams}&cache_invalidation_key=${cacheInvalidationKey}`
        } else {
            // TODO: We should never land in this case; Remove this if Sentry doesn't unexpectedly capture this.
            Sentry.captureException(new Error('buildPeopleUrl used for non-trends funnel'), {
                extra: { filters },
            })
        }
    } else if (isPathsFilter(filters)) {
        const cleanedParams = cleanFilters(filters)
        const pathParams = toParams(cleanedParams)
        return `api/person/path/?${pathParams}&cache_invalidation_key=${cacheInvalidationKey}`
    } else {
        // TODO: We should never land in this case; Remove this if Sentry doesn't unexpectedly capture this.
        Sentry.captureException(new Error('buildPeopleUrl used for unsupported filters'), {
            extra: { filters },
        })
    }
}

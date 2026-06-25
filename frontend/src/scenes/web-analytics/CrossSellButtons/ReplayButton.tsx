import posthog from 'posthog-js'

import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { recordWebAnalyticsInteraction } from 'scenes/web-analytics/achievements/recordInteraction'
import { BREAKDOWN_NULL_DISPLAY } from 'scenes/web-analytics/common'

import {
    ProductIntentContext,
    ProductKey,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFiltersGroupValue,
} from '~/types'

import { InteractionKindEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

/**
 * Build a property filter for a breakdown value. When the value is the
 * BREAKDOWN_NULL_DISPLAY placeholder ("(none)"), the property isn't literally
 * set to "(none)" — it just isn't set — so use IsNotSet instead of an exact
 * match.
 */
const buildBreakdownPropertyFilter = (
    key: string,
    type: PropertyFilterType.Event | PropertyFilterType.Session | PropertyFilterType.Person,
    value: string
): AnyPropertyFilter => {
    if (value === BREAKDOWN_NULL_DISPLAY) {
        return {
            key,
            type,
            value: null,
            operator: PropertyOperator.IsNotSet,
        } as AnyPropertyFilter
    }
    return {
        key,
        type,
        value: [value],
        operator: PropertyOperator.Exact,
    } as AnyPropertyFilter
}

/**
 * Map breakdown types to their corresponding property filter type
 * Outside the replayButton function.
 *
 * Prefer not to use Person properties, are the user might be using anonymous events.
 */
const BREAKDOWN_TYPE_MAP: Partial<Record<WebStatsBreakdown, PropertyFilterType.Event | PropertyFilterType.Session>> = {
    [WebStatsBreakdown.DeviceType]: PropertyFilterType.Event,
    [WebStatsBreakdown.InitialPage]: PropertyFilterType.Session,
    [WebStatsBreakdown.ExitPage]: PropertyFilterType.Session,
    [WebStatsBreakdown.Page]: PropertyFilterType.Event,
    [WebStatsBreakdown.Browser]: PropertyFilterType.Event,
    [WebStatsBreakdown.OS]: PropertyFilterType.Event,
    [WebStatsBreakdown.InitialChannelType]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialReferringDomain]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialReferringURL]: PropertyFilterType.Event,
    [WebStatsBreakdown.InitialUTMSource]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialUTMCampaign]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialUTMMedium]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialUTMContent]: PropertyFilterType.Session,
    [WebStatsBreakdown.InitialUTMTerm]: PropertyFilterType.Session,
    [WebStatsBreakdown.FrustrationMetrics]: PropertyFilterType.Event,
}

/**
 * Map breakdown types to their corresponding property filter key
 * Outside the replayButton function
 */
const BREAKDOWN_KEY_MAP: Partial<Record<WebStatsBreakdown, string>> = {
    [WebStatsBreakdown.DeviceType]: '$device_type',
    [WebStatsBreakdown.InitialPage]: '$entry_pathname',
    [WebStatsBreakdown.ExitPage]: '$end_pathname',
    [WebStatsBreakdown.Page]: '$pathname',
    [WebStatsBreakdown.Browser]: '$browser',
    [WebStatsBreakdown.OS]: '$os',
    [WebStatsBreakdown.InitialChannelType]: '$channel_type',
    [WebStatsBreakdown.InitialReferringDomain]: '$entry_referring_domain',
    [WebStatsBreakdown.InitialReferringURL]: '$session_entry_referrer',
    [WebStatsBreakdown.InitialUTMSource]: '$entry_utm_source',
    [WebStatsBreakdown.InitialUTMCampaign]: '$entry_utm_campaign',
    [WebStatsBreakdown.InitialUTMMedium]: '$entry_utm_medium',
    [WebStatsBreakdown.InitialUTMContent]: '$entry_utm_content',
    [WebStatsBreakdown.InitialUTMTerm]: '$entry_utm_term',
    [WebStatsBreakdown.FrustrationMetrics]: '$pathname',
}

interface ReplayButtonProps {
    date_from: string
    date_to: string
    breakdownBy: WebStatsBreakdown
    value: string
    /** Dashboard-level filters applied to the source web analytics query. Must be forwarded so the
     *  recordings page narrows down to the same population the row count reflects. */
    properties?: WebAnalyticsPropertyFilters
    /** Web analytics filters test accounts by default; session replay doesn't. Forward it so the
     *  recordings page matches the row count. */
    filter_test_accounts?: boolean
}

export const ReplayButton = ({
    date_from,
    date_to,
    breakdownBy,
    value,
    properties,
    filter_test_accounts,
}: ReplayButtonProps): JSX.Element => {
    const extraFilters: UniversalFiltersGroupValue[] = (properties ?? []) as UniversalFiltersGroupValue[]

    /** Compose the recordings filter from the per-breakdown property filters plus the dashboard-level
     *  `properties` and `filter_test_accounts` that every branch needs to forward. */
    const buildFilters = (breakdownValues: UniversalFiltersGroupValue[]): Partial<RecordingUniversalFilters> => {
        const innerValues = [...breakdownValues, ...extraFilters]
        return {
            date_from,
            date_to,
            filter_test_accounts,
            ...(innerValues.length
                ? {
                      filter_group: {
                          type: FilterLogicalOperator.And,
                          values: [{ type: FilterLogicalOperator.And, values: innerValues }],
                      },
                  }
                : {}),
        }
    }

    const renderButton = (filters: Partial<RecordingUniversalFilters>): JSX.Element => (
        <div onClick={handleClick}>
            <ViewRecordingsPlaylistButton filters={filters} type="tertiary" size="xsmall" />
        </div>
    )

    const handleClick = (e: React.MouseEvent): void => {
        e.stopPropagation()
        posthog.capture('web_analytics_recording_opened', { breakdown_by: breakdownBy })
        recordWebAnalyticsInteraction(InteractionKindEnumApi.Recording)
        void addProductIntentForCrossSell({
            from: ProductKey.WEB_ANALYTICS,
            to: ProductKey.SESSION_REPLAY,
            intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
        })
    }

    /** If value is empty - just open session replay home page, but still forward dashboard
     *  filters so the recordings list isn't wider than what the user is looking at. */
    if (value === '') {
        return renderButton(buildFilters([]))
    }

    /** View port is a unique case, so we need to handle it differently */
    if (breakdownBy === WebStatsBreakdown.Viewport) {
        return renderButton(
            buildFilters([
                {
                    key: '$viewport_width',
                    type: PropertyFilterType.Event,
                    value: [value[0]],
                    operator: PropertyOperator.Exact,
                },
                {
                    key: '$viewport_height',
                    type: PropertyFilterType.Event,
                    value: [value[1]],
                    operator: PropertyOperator.Exact,
                },
            ])
        )
    }

    /** UTM source, medium, campaign is a unique case, so we need to handle it differently, as combining them with AND */
    if (breakdownBy === WebStatsBreakdown.InitialUTMSourceMediumCampaign) {
        const values = value.split(' / ')
        return renderButton(
            buildFilters([
                buildBreakdownPropertyFilter(
                    '$entry_utm_source',
                    PropertyFilterType.Session,
                    values[0] ?? BREAKDOWN_NULL_DISPLAY
                ),
                buildBreakdownPropertyFilter(
                    '$entry_utm_medium',
                    PropertyFilterType.Session,
                    values[1] ?? BREAKDOWN_NULL_DISPLAY
                ),
                buildBreakdownPropertyFilter(
                    '$entry_utm_campaign',
                    PropertyFilterType.Session,
                    values[2] ?? BREAKDOWN_NULL_DISPLAY
                ),
            ])
        )
    }

    /** Referring URL is displayed with query params stripped, so use regex to match the raw value */
    if (breakdownBy === WebStatsBreakdown.InitialReferringURL) {
        const escapedValue = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        return renderButton(
            buildFilters([
                {
                    key: '$session_entry_referrer',
                    type: PropertyFilterType.Event,
                    value: [`^${escapedValue}($|\\?|#)`],
                    operator: PropertyOperator.Regex,
                },
            ])
        )
    }

    const type = BREAKDOWN_TYPE_MAP[breakdownBy] || PropertyFilterType.Person
    const key = BREAKDOWN_KEY_MAP[breakdownBy]
    if (!key || !type) {
        /** If the breakdown is not supported, return an empty element */
        return <></>
    }

    return renderButton(buildFilters([buildBreakdownPropertyFilter(key, type, value)]))
}

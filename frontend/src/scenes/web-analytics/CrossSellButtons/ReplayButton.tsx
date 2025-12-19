import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

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
}

export const ReplayButton = ({ date_from, date_to, breakdownBy, value }: ReplayButtonProps): JSX.Element => {
    const handleClick = (e: React.MouseEvent): void => {
        e.stopPropagation()
        void addProductIntentForCrossSell({
            from: ProductKey.WEB_ANALYTICS,
            to: ProductKey.SESSION_REPLAY,
            intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
        })
    }

    /** If value is empty - just open session replay home page */
    if (value === '') {
        const filters: Partial<RecordingUniversalFilters> = {
            date_from,
            date_to,
        }
        return (
            <div onClick={handleClick}>
                <ViewRecordingsPlaylistButton filters={filters} type="tertiary" size="xsmall" />
            </div>
        )
    }

    /** View port is a unique case, so we need to handle it differently */
    if (breakdownBy === WebStatsBreakdown.Viewport) {
        const filters: Partial<RecordingUniversalFilters> = {
            date_from,
            date_to,
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
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
                        ],
                    },
                ],
            },
        }
        return (
            <div onClick={handleClick}>
                <ViewRecordingsPlaylistButton filters={filters} type="tertiary" size="xsmall" />
            </div>
        )
    }

    /** UTM source, medium, campaign is a unique case, so we need to handle it differently, as combining them with AND */
    if (breakdownBy === WebStatsBreakdown.InitialUTMSourceMediumCampaign) {
        const values = value.split(' / ')
        const filters: Partial<RecordingUniversalFilters> = {
            date_from,
            date_to,
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key: '$entry_utm_source',
                                type: PropertyFilterType.Session,
                                value: [values[0] || ''],
                                operator: PropertyOperator.Exact,
                            },
                            {
                                key: '$entry_utm_medium',
                                type: PropertyFilterType.Session,
                                value: [values[1] || ''],
                                operator: PropertyOperator.Exact,
                            },
                            {
                                key: '$entry_utm_campaign',
                                type: PropertyFilterType.Session,
                                value: [values[2] || ''],
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ],
            },
        }
        return (
            <div onClick={handleClick}>
                <ViewRecordingsPlaylistButton filters={filters} type="tertiary" size="xsmall" />
            </div>
        )
    }

    const type = BREAKDOWN_TYPE_MAP[breakdownBy] || PropertyFilterType.Person
    const key = BREAKDOWN_KEY_MAP[breakdownBy]
    if (!key || !type) {
        /** If the breakdown is not supported, return an empty element */
        return <></>
    }

    /** Render the button */
    const filters: Partial<RecordingUniversalFilters> = {
        date_from,
        date_to,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: key,
                            type: type,
                            value: [value],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
        },
    }
    return (
        <div onClick={handleClick}>
            <ViewRecordingsPlaylistButton filters={filters} type="tertiary" size="xsmall" />
        </div>
    )
}

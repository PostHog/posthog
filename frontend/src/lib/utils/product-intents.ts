import api from 'lib/api'

import type { ProductKey, TeamType } from '~/types'

export enum ProductIntentContext {
    // Onboarding
    ONBOARDING_PRODUCT_SELECTED_PRIMARY = 'onboarding product selected - primary',
    ONBOARDING_PRODUCT_SELECTED_SECONDARY = 'onboarding product selected - secondary',
    QUICK_START_PRODUCT_SELECTED = 'quick start product selected',

    // Data Warehouse
    SELECTED_CONNECTOR = 'selected connector',
    SQL_EDITOR_EMPTY_STATE = 'sql editor empty state',
    DATA_WAREHOUSE_SOURCES_TABLE = 'data warehouse sources table',

    // Experiments
    EXPERIMENT_CREATED = 'experiment created',

    // Feature Flags
    FEATURE_FLAG_CREATED = 'feature flag created',

    // Session Replay
    SESSION_REPLAY_SET_FILTERS = 'session_replay_set_filters',

    // Error Tracking
    ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED = 'error_tracking_exception_autocapture_enabled',
    ERROR_TRACKING_ISSUE_SORTING = 'error_tracking_issue_sorting',
    ERROR_TRACKING_DOCS_VIEWED = 'error_tracking_docs_viewed',

    // LLM Analytics
    LLM_ANALYTICS_VIEWED = 'llm_analytics_viewed',
    LLM_ANALYTICS_DOCS_VIEWED = 'llm_analytics_docs_viewed',

    /*
    Cross Sells
    */

    // Product Analytics
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic filter empty state',
    CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON = 'create_experiment_from_funnel_button',

    // Web Analytics
    WEB_ANALYTICS_INSIGHT = 'web_analytics_insight',
    WEB_VITALS_INSIGHT = 'web_vitals_insight',
    WEB_ANALYTICS_RECORDINGS = 'web_analytics_recordings',
    WEB_ANALYTICS_ERROR_TRACKING = 'web_analytics_error_tracking',
    WEB_ANALYTICS_ERRORS = 'web_analytics_errors',
    WEB_ANALYTICS_FRUSTRATING_PAGES = 'web_analytics_frustrating_pages',
    // Actions
    ACTION_VIEW_RECORDINGS = 'action_view_recordings',

    // Persons
    PERSON_VIEW_RECORDINGS = 'person_view_recordings',

    // Feature Flags
    FEATURE_FLAG_CREATE_INSIGHT = 'feature_flag_create_insight',
    FEATURE_FLAG_VIEW_RECORDINGS = 'feature_flag_view_recordings',

    // Early Access Features
    EARLY_ACCESS_FEATURE_VIEW_RECORDINGS = 'early_access_feature_view_recordings',

    // Surveys
    SURVEYS_VIEWED = 'surveys_viewed', // accessed surveys page
    SURVEY_CREATED = 'survey_created',
    SURVEY_LAUNCHED = 'survey_launched',
    SURVEY_VIEWED = 'survey_viewed',
    SURVEY_COMPLETED = 'survey_completed', // stop survey
    SURVEY_RESUMED = 'survey_resumed',
    SURVEY_ARCHIVED = 'survey_archived',
    SURVEY_UNARCHIVED = 'survey_unarchived',
    SURVEY_DELETED = 'survey_deleted',
    SURVEY_DUPLICATED = 'survey_duplicated',
    SURVEY_BULK_DUPLICATED = 'survey_bulk_duplicated',
    SURVEY_EDITED = 'survey_edited',
    SURVEY_ANALYZED = 'survey_analyzed',

    // Nav Panel Advertisement
    NAV_PANEL_ADVERTISEMENT_CLICKED = 'nav_panel_advertisement_clicked',
}

export type ProductIntentMetadata = Record<string, unknown>

export type ProductIntentProperties = {
    product_type: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntent(properties: ProductIntentProperties): Promise<TeamType | null> {
    return api.productIntents.update(properties)
}

export type ProductCrossSellProperties = {
    from: ProductKey
    to: ProductKey
    intent_context: ProductIntentContext
    metadata?: ProductIntentMetadata
}

export function addProductIntentForCrossSell(properties: ProductCrossSellProperties): Promise<TeamType | null> {
    return api.productIntents.update({
        product_type: properties.to,
        intent_context: properties.intent_context,
        metadata: {
            ...properties.metadata,
            from: properties.from,
            to: properties.to,
            type: 'cross_sell',
        },
    })
}

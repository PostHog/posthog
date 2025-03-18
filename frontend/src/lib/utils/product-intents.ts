import api from 'lib/api'

import type { ProductKey, TeamType } from '~/types'

export enum ProductIntentContext {
    // Onboarding
    ONBOARDING_PRODUCT_SELECTED_PRIMARY = 'onboarding product selected - primary',
    ONBOARDING_PRODUCT_SELECTED_SECONDARY = 'onboarding product selected - secondary',
    QUICK_START_PRODUCT_SELECTED = 'quick start product selected',

    // Data Warehouse
    SELECTED_CONNECTOR = 'selected connector',

    // Experiments
    EXPERIMENT_CREATED = 'experiment created',

    // Feature Flags
    FEATURE_FLAG_CREATED = 'feature flag created',

    // Error Tracking
    ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED = 'error_tracking_exception_autocapture_enabled',
    ERROR_TRACKING_USER_GROUP_CREATED = 'error_tracking_user_group_created',
    ERROR_TRACKING_ALERT_CREATED = 'error_tracking_alert_created',

    // TODO: can only be tracked server side. Is there a helper or just copy logic from api/team.py
    // ERROR_TRACKING_UPLOADED_SOURCE_MAP = 'error_tracking_uploaded_source_map',

    // TODO: should these be intents or are they just regular product usage?
    // ERROR_TRACKING_FILTERED_ISSUES = 'error_tracking_filtered_issues',
    // ERROR_TRACKING_ISSUE_ASSIGN = 'error_tracking_issue_assign',
    // ERROR_TRACKING_ISSUE_SET_STATUS = 'error_tracking_issue_set_status',
    // ERROR_TRACKING_VIEWED_ISSUE = 'error_tracking_viewed_issue',

    /*
    Cross Sells
    */

    // Product Analytics
    TAXONOMIC_FILTER_EMPTY_STATE = 'taxonomic filter empty state',
    CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON = 'create_experiment_from_funnel_button',
    PRODUCT_ANALYTICS_VIEW_ISSUE_FROM_EVENT = 'product_analytics_view_issue_from_event',
    PRODUCT_ANALYTICS_VIEW_RECORDING_FROM_EVENT = 'product_analytics_view_recording_from_event',

    // Web Analytics
    WEB_ANALYTICS_INSIGHT = 'web_analytics_insight',
    WEB_VITALS_INSIGHT = 'web_vitals_insight',
    WEB_ANALYTICS_RECORDINGS = 'web_analytics_recordings',
    WEB_ANALYTICS_ERROR_TRACKING = 'web_analytics_error_tracking',
    WEB_ANALYTICS_ERRORS = 'web_analytics_errors',

    // Actions
    ACTION_VIEW_RECORDINGS = 'action_view_recordings',

    // Persons
    PERSON_VIEW_RECORDINGS = 'person_view_recordings',

    // Feature Flags
    FEATURE_FLAG_CREATE_INSIGHT = 'feature_flag_create_insight',
    FEATURE_FLAG_VIEW_RECORDINGS = 'feature_flag_view_recordings',

    // Early Access Features
    EARLY_ACCESS_FEATURE_VIEW_RECORDINGS = 'early_access_feature_view_recordings',
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

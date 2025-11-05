import { FileSystemIconType } from '~/queries/schema/schema-general'

export function getIconTypeFromUrl(href: string): FileSystemIconType {
    if (!href) {
        return 'arrow_right'
    }

    // Remove query parameters and fragments for cleaner matching
    const cleanPath = href.split('?')[0].split('#')[0]

    // Match against known PostHog URL patterns
    if (cleanPath.includes('/dashboard')) {
        return 'dashboard'
    }
    if (cleanPath.includes('/activity')) {
        return 'event'
    }
    if (cleanPath.includes('/notebook')) {
        return 'notebook'
    }
    if (cleanPath.includes('/insights')) {
        return 'product_analytics'
    }
    if (cleanPath.includes('/events')) {
        return 'event_definition'
    }
    if (cleanPath.includes('/persons')) {
        return 'persons'
    }
    if (cleanPath.includes('/person/')) {
        return 'user'
    }
    if (cleanPath.includes('/groups/')) {
        return 'group'
    }
    if (cleanPath.includes('/cohorts')) {
        return 'cohort'
    }
    if (cleanPath.includes('/feature_flags')) {
        return 'feature_flag'
    }
    if (cleanPath.includes('/early_access_features')) {
        return 'early_access_feature'
    }
    if (cleanPath.includes('/experiments')) {
        return 'experiment'
    }
    if (cleanPath.includes('/surveys')) {
        return 'survey'
    }
    if (cleanPath.includes('/session-recordings')) {
        return 'session_replay'
    }
    if (cleanPath.includes('/replay/')) {
        return 'session_replay'
    }
    if (cleanPath.includes('/data-pipeline')) {
        return 'data_pipeline'
    }
    if (cleanPath.includes('/data-warehouse')) {
        return 'data_warehouse'
    }
    if (cleanPath.includes('/sql')) {
        return 'sql_editor'
    }
    if (cleanPath.includes('/heatmaps')) {
        return 'heatmap'
    }
    if (cleanPath.includes('/web-performance')) {
        return 'web_analytics'
    }
    if (cleanPath.includes('/error_tracking')) {
        return 'error_tracking'
    }
    if (cleanPath.includes('/data-management/properties')) {
        return 'property_definition'
    }
    if (cleanPath.includes('/data-management/events')) {
        return 'event_definition'
    }
    if (cleanPath.includes('/data-management/annotations')) {
        return 'annotation'
    }
    if (cleanPath.includes('/data-management/revenue')) {
        return 'revenue_analytics'
    }
    if (cleanPath.includes('/data-management/ingestion-warnings')) {
        return 'ingestion_warning'
    }
    if (cleanPath.includes('/data-management/marketing-analytics')) {
        return 'marketing_settings'
    }
    if (cleanPath.includes('/organization')) {
        return 'group'
    }
    if (cleanPath.includes('/web')) {
        return 'web_analytics'
    }
    if (cleanPath.includes('/logs')) {
        return 'logs'
    }
    if (cleanPath.includes('/workflows')) {
        return 'workflows'
    }
    if (cleanPath.includes('/notebooks')) {
        return 'notebook'
    }
    if (cleanPath.includes('/actions')) {
        return 'action'
    }
    if (cleanPath.includes('/comments')) {
        return 'comment'
    }
    if (cleanPath.includes('/annotations')) {
        return 'annotation'
    }
    if (cleanPath.includes('/events')) {
        return 'event'
    }
    if (cleanPath.includes('/event_definitions')) {
        return 'event_definition'
    }
    if (cleanPath.includes('/property_definitions')) {
        return 'property_definition'
    }
    if (cleanPath.includes('/persons')) {
        return 'persons'
    }
    if (cleanPath.includes('/person/')) {
        return 'user'
    }
    if (cleanPath.includes('/cohorts')) {
        return 'cohort'
    }
    if (cleanPath.includes('/feature_flags')) {
        return 'feature_flag'
    }
    if (cleanPath.includes('/early_access_features')) {
        return 'early_access_feature'
    }
    if (cleanPath.includes('/experiments')) {
        return 'experiment'
    }
    if (cleanPath.includes('/surveys')) {
        return 'survey'
    }
    if (cleanPath.includes('/session_recordings')) {
        return 'session_replay'
    }
    if (cleanPath.includes('/replay/')) {
        return 'session_replay'
    }
    if (cleanPath.includes('/pipeline')) {
        return 'data_pipeline'
    }
    if (cleanPath.includes('/customer_analytics')) {
        return 'group'
    }
    if (cleanPath.includes('/endpoints')) {
        return 'endpoints'
    }
    if (cleanPath.includes('/links')) {
        return 'link'
    }
    if (cleanPath.includes('/llm-analytics')) {
        return 'llm_analytics'
    }
    if (cleanPath.includes('/revenue_analytics')) {
        return 'revenue_analytics'
    }
    if (cleanPath.includes('/tasks')) {
        return 'task'
    }
    if (cleanPath.includes('/user_interviews')) {
        return 'user_interview'
    }
    if (cleanPath.includes('/toolbar')) {
        return 'toolbar'
    }
    if (cleanPath.includes('/settings')) {
        return 'gear'
    }
    if (cleanPath.includes('/project/')) {
        return 'home'
    }

    // Default to arrow_right for unknown internal URLs
    return 'arrow_right'
}

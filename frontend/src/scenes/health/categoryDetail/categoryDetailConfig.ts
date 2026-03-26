import { urls } from 'scenes/urls'

import type { HealthIssueCategory } from '../healthCategories'

export interface CategoryDetailConfig {
    docsUrl?: string
    deepDiveUrl?: string
    deepDiveLabel?: string
    guidance?: string
}

export const CATEGORY_DETAIL_CONFIG: Partial<Record<HealthIssueCategory, CategoryDetailConfig>> = {
    ingestion: {
        docsUrl: 'https://posthog.com/docs/data/ingestion-warnings',
        guidance:
            'Ingestion issues mean some events may be delayed or missing. Check for warnings and address any lag.',
    },
    sdk: {
        docsUrl: 'https://posthog.com/docs/libraries',
        deepDiveUrl: urls.sdkDoctor(),
        deepDiveLabel: 'Open SDK doctor',
        guidance: 'Outdated SDKs miss bug fixes and new features. Update to the latest version for best results.',
    },
    web_analytics: {
        docsUrl: 'https://posthog.com/docs/web-analytics',
        guidance: 'These checks ensure your web analytics data is complete and accurate.',
    },
    pipelines: {
        docsUrl: 'https://posthog.com/docs/cdp',
        deepDiveUrl: urls.pipelineStatus(),
        deepDiveLabel: 'Open pipeline status',
        guidance: 'Pipeline failures mean data may not be flowing to your destinations correctly.',
    },
    data_modeling: {
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        guidance: 'Materialized view failures may affect query performance and data freshness.',
    },
}

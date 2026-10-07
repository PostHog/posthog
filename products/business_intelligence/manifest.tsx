import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { HogQLFilters, ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Business intelligence',
    scenes: {
        BusinessIntelligence: {
            name: 'Business intelligence',
            import: () => import('./frontend/BusinessIntelligenceScene'),
            projectBased: true,
            layout: 'app-raw-no-header',
            hideProjectNotice: true,
            description: 'Explore data and build charts with a visual worksheet.',
            iconType: 'business_intelligence',
        },
    },
    routes: {
        '/bi': ['BusinessIntelligence', 'businessIntelligence'],
    },
    redirects: {},
    urls: {
        businessIntelligence: ({
            insightShortId,
            viewId,
            dashboard,
            filters,
        }: {
            insightShortId?: string
            viewId?: string
            dashboard?: number
            filters?: HogQLFilters
        } = {}): string => {
            const search = new URLSearchParams()
            if (insightShortId) {
                search.set('open_insight', insightShortId)
            } else if (viewId) {
                search.set('open_view', viewId)
            }
            if (dashboard) {
                search.set('dashboard', String(dashboard))
            }
            const hash = filters ? `#filters=${encodeURIComponent(JSON.stringify(filters))}` : ''
            const query = search.toString()
            return `/bi${query ? `?${query}` : ''}${hash}`
        },
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Business intelligence',
            intents: [],
            category: ProductItemCategory.DATA,
            iconType: 'business_intelligence',
            iconColor: [
                'var(--color-product-business-intelligence-light)',
                'var(--color-product-business-intelligence-dark)',
            ],
            href: urls.businessIntelligence(),
            searchKeywords: ['bi', 'pivot table', 'chart builder'],
            flag: FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
            sceneKey: 'BusinessIntelligence',
        },
    ],
}

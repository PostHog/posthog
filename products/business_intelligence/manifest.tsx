import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { HogQLFilters, ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Business intelligence',
    scenes: {
        BusinessIntelligenceHome: {
            name: 'Worksheets',
            import: () => import('./frontend/BIWorksheetsScene'),
            projectBased: true,
            iconType: 'business_intelligence',
        },
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
        '/bi': ['BusinessIntelligenceHome', 'businessIntelligence'],
        '/bi/new': ['BusinessIntelligence', 'businessIntelligenceNew'],
        '/bi/:insightShortId': ['BusinessIntelligence', 'businessIntelligenceWorksheet'],
    },
    redirects: {},
    urls: {
        businessIntelligenceNew: (): string => '/bi/new',
        businessIntelligenceWorksheet: (insightShortId: string): string => `/bi/${encodeURIComponent(insightShortId)}`,
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
    fileSystemTypes: {
        'insight/bi': {
            name: 'Worksheet',
            iconType: 'business_intelligence',
            href: (ref: string) => urls.businessIntelligenceWorksheet(ref),
            listHref: () => urls.businessIntelligence(),
            filterKey: 'insight',
        },
    },
    treeItemsNew: [
        {
            path: 'Worksheet',
            type: 'insight',
            iconType: 'business_intelligence',
            href: `${urls.businessIntelligenceNew()}#q=`,
            flag: FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
            sceneKeys: ['BusinessIntelligence', 'BusinessIntelligenceHome'],
        },
    ],
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
            flag: FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
            sceneKey: 'BusinessIntelligence',
        },
    ],
}

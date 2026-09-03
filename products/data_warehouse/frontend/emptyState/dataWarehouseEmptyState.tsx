import * as organizedPng from '@posthog/brand/hoggies/png/organized'
import { IconDatabase } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { DataWarehousePreview } from './DataWarehousePreview'
import { dataWarehouseSetupLogic } from './dataWarehouseSetupLogic'

const HedgehogOrganized = pngHoggie(organizedPng)

export const dataWarehouseEmptyState: SceneProductEmptyState = {
    statusLogic: dataWarehouseSetupLogic,
    config: {
        productKey: ProductKey.DATA_WAREHOUSE,
        productName: 'Data warehouse',
        icon: <IconDatabase />,
        accentColor: 'var(--color-product-data-warehouse-light)',
        accentColorDark: 'var(--color-product-data-warehouse-dark)',
        hedgehog: HedgehogOrganized,
        text: {
            'needs-setup': {
                headline: 'Query your business data next to your product data',
                lead: 'Sync tables from Postgres, MySQL, Stripe, Hubspot, and more into PostHog, then join them with your events in SQL. Revenue next to retention, support tickets next to sessions.',
                hint: 'Wizard detects your database and connects it for you:',
            },
        },
        wizard: { slug: 'warehouse', pinProjectId: true },
        primaryAction: {
            label: 'New source',
            to: urls.dataPipelinesNew('source'),
            // pinned: the scene's own New source button carries this attr
            dataAttr: 'new-source',
        },
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        previewLabel: 'Your sources, once connected',
        Preview: DataWarehousePreview,
        // Skipping would reveal three empty source tables; connecting one is the only next step.
        skippable: false,
    },
}

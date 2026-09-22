import * as stampApprovedPng from '@posthog/brand/hoggies/png/stamp-approved'
import { IconBook } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { DataCatalogPreview } from './DataCatalogPreview'
import { DataCatalogPrimaryAction } from './DataCatalogPrimaryAction'
import { dataCatalogSetupLogic } from './dataCatalogSetupLogic'

const HedgehogStampApproved = pngHoggie(stampApprovedPng)

export const dataCatalogEmptyState: SceneProductEmptyState = {
    statusLogic: dataCatalogSetupLogic,
    config: {
        productKey: ProductKey.DATA_CATALOG,
        productName: 'Data catalog',
        icon: <IconBook />,
        accentColor: 'var(--color-product-data-catalog-light)',
        accentColorDark: 'var(--color-product-data-catalog-dark)',
        hedgehog: HedgehogStampApproved,
        text: {
            'needs-setup': {
                headline: 'Settle what each number means, once',
                lead: 'A catalog metric is one agreed definition of a number: its name, the query behind it, and who approved it. Define active users or revenue here, and everyone reads the same definition instead of rebuilding it slightly differently each time.',
            },
        },
        PrimaryAction: DataCatalogPrimaryAction,
        docsUrl: 'https://posthog.com/docs/semantic-layer',
        previewLabel: 'Your catalog, once defined',
        Preview: DataCatalogPreview,
    },
}

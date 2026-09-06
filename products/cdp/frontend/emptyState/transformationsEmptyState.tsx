import * as transformerPng from '@posthog/brand/hoggies/png/transformer'
import { IconShuffle } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { TransformationsPreview } from './TransformationsPreview'
import { transformationsSetupLogic } from './transformationsSetupLogic'

const HedgehogTransformer = pngHoggie(transformerPng)

export const transformationsEmptyState: SceneProductEmptyState = {
    statusLogic: transformationsSetupLogic,
    config: {
        productKey: ProductKey.PIPELINE_TRANSFORMATIONS,
        productName: 'Transformations',
        icon: <IconShuffle />,
        accentColor: 'var(--color-product-data-pipeline-light)',
        accentColorDark: 'var(--color-product-data-pipeline-dark)',
        hedgehog: HedgehogTransformer,
        text: {
            'needs-setup': {
                headline: 'Clean up events before they are stored',
                lead: 'A transformation runs on every event as it is ingested, before anything else sees it. Use one to add GeoIP location, drop properties you do not want to keep, filter out bot traffic, or fix a property name the SDK got wrong. Start from a template, or write your own in Hog.',
            },
        },
        primaryAction: {
            label: 'Create your first transformation',
            to: urls.dataPipelinesNew('transformation'),
            dataAttr: 'new-transformation',
        },
        docsUrl: 'https://posthog.com/docs/cdp/transformations',
        previewLabel: 'Your transformations, once enabled',
        Preview: TransformationsPreview,
    },
}

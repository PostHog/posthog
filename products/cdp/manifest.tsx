import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'CDP',
    treeItemsNew: [
        {
            path: `Data/Source`,
            type: 'hog_function/source',
            href: urls.dataPipelinesNew('source'),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            sceneKeys: ['HogFunction'],
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: urls.dataPipelinesNew('destination'),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            sceneKeys: ['HogFunction'],
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: urls.dataPipelinesNew('transformation'),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            sceneKeys: ['HogFunction'],
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: urls.dataPipelinesNew('site_app'),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            sceneKeys: ['HogFunction'],
        },
    ],
    treeItemsProducts: [
        {
            path: `Data pipelines`,
            intents: [ProductKey.PIPELINE_DESTINATIONS, ProductKey.PIPELINE_TRANSFORMATIONS, ProductKey.SITE_APPS],
            category: 'Tools',
            type: 'hog_function',
            iconType: 'data_pipeline',
            iconColor: ['var(--color-product-data-pipeline-light)'],
            href: urls.dataPipelines(),
            sceneKey: 'DataPipelines',
            sceneKeys: ['DataPipelines'],
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Data pipelines',
            category: 'Tools',
            type: 'hog_function',
            iconType: 'data_pipeline',
            iconColor: ['var(--color-product-data-pipeline-light)'],
            href: urls.dataPipelines(),
            sceneKey: 'DataPipelines',
            sceneKeys: ['DataPipelines'],
        },
        {
            path: `Transformations`,
            category: 'Pipeline',
            type: 'hog_function/transformation',
            iconType: 'data_pipeline_metadata',
            href: urls.dataPipelines('transformations'),
            sceneKey: 'DataPipelines',
            sceneKeys: ['DataPipelines'],
        },
        {
            path: `Destinations`,
            category: 'Pipeline',
            type: 'hog_function/destination',
            iconType: 'data_pipeline_metadata',
            href: urls.dataPipelines('destinations'),
            sceneKey: 'DataPipelines',
            sceneKeys: ['DataPipelines'],
        },
        {
            path: 'Ingestion warnings',
            category: 'Pipeline',
            iconType: 'ingestion_warning',
            href: urls.ingestionWarnings(),
            sceneKey: 'IngestionWarnings',
            sceneKeys: ['IngestionWarnings'],
        },
    ],
}

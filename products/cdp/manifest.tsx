import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'CDP',
    scenes: {
        Transformations: {
            import: () => import('../../frontend/src/scenes/data-pipelines/TransformationsScene'),
            projectBased: true,
            name: 'Transformations',
            description:
                'Transformations let you modify, filter, and enrich event data to improve data quality, privacy, and consistency.',
            activityScope: 'HogFunction',
            iconType: 'data_pipeline',
        },
        EventFiltering: {
            import: () => import('../../frontend/src/scenes/data-pipelines/event-filtering/EventFilterScene'),
            projectBased: true,
            name: 'Event ingestion filtering',
            description: 'Drop events at ingestion time based on event metadata.',
            iconType: 'data_pipeline',
        },
    },
    routes: {
        '/transformations': ['Transformations', 'transformations'],
        '/event-filtering': ['EventFiltering', 'eventFiltering'],
    },
    urls: {
        transformations: (): string => '/transformations',
        eventFiltering: (): string => '/event-filtering',
    },
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
            path: `Data/Web script`,
            type: 'hog_function/site_app',
            href: urls.webScriptsNew(),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            sceneKeys: ['HogFunction'],
        },
    ],
    treeItemsProducts: [
        {
            path: 'Web scripts',
            intents: [ProductKey.SITE_APPS],
            category: ProductItemCategory.TOOLS,
            type: 'hog_function',
            iconType: 'data_pipeline',
            iconColor: ['var(--color-product-data-pipeline-light)'],
            href: urls.webScripts(),
            sceneKey: 'WebScripts',
            sceneKeys: ['WebScripts'],
        },
    ],
    treeItemsMetadata: [
        {
            path: `Transformations`,
            category: 'Pipeline',
            type: 'hog_function/transformation',
            iconType: 'data_pipeline_metadata',
            href: urls.transformations(),
            sceneKey: 'Transformations',
            sceneKeys: ['Transformations'],
        },
        {
            path: 'Event ingestion filtering',
            category: 'Pipeline',
            type: 'event_filter',
            iconType: 'data_pipeline_metadata',
            href: urls.eventFiltering(),
            sceneKey: 'EventFiltering',
            sceneKeys: ['EventFiltering'],
        },
        {
            path: `Destinations`,
            category: 'Pipeline',
            type: 'hog_function/destination',
            iconType: 'data_pipeline_metadata',
            href: urls.destinations(),
            sceneKey: 'Destinations',
            sceneKeys: ['Destinations'],
        },
        {
            path: 'Event ingestion warnings',
            category: 'Pipeline',
            iconType: 'ingestion_warning',
            href: urls.ingestionWarnings(),
            sceneKey: 'IngestionWarnings',
            sceneKeys: ['IngestionWarnings'],
        },
    ],
}

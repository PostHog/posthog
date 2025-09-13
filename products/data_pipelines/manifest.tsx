import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Data Pipelines',
    urls: {
        dataPipelines: (tab?: string): string => `/data-pipelines${tab ? `/${tab}` : ''}`,
    },
    fileSystemTypes: {
        hog_function: {
            name: 'Data pipeline',
            iconType: 'data_pipeline' as FileSystemIconType,
            href: () => urls.dataPipelines(),
            iconColor: ['var(--color-product-data-pipeline-light)'],
            filterKey: 'hog_function',
        },
    },
    treeItemsProducts: [
        {
            path: 'Data pipelines',
            category: 'Tools',
            type: 'hog_function',
            iconType: 'data_pipeline' as FileSystemIconType,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
            href: urls.dataPipelines(),
        },
    ],
}

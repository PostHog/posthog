import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Cohorts',
    urls: {
        cohort: (id: string | number): string => `/cohorts/${id}`,
        cohorts: (): string => '/cohorts',
    },
    fileSystemTypes: {
        cohort: {
            name: 'Cohort',
            iconType: 'cohort' as FileSystemIconType,
            href: (ref: string) => urls.cohort(ref),
            filterKey: 'cohort',
            iconColor: ['var(--color-product-cohorts-light)'] as FileSystemIconColor,
        },
    },
    treeItemsNew: [
        {
            path: `Cohort`,
            type: 'cohort',
            href: urls.cohort('new'),
            iconType: 'cohort' as FileSystemIconType,
            iconColor: ['var(--color-product-cohorts-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}

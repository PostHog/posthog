import { IconPeople } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Cohorts',
    urls: {
        cohort: (id: string | number): string => `/cohorts/${id}`,
        cohorts: (): string => '/cohorts',
    },
    fileSystemTypes: {
        cohort: {
            name: 'Cohort',
            icon: <IconPeople />,
            href: (ref: string) => urls.cohort(ref),
            filterKey: 'cohort',
        },
    },
    treeItemsNew: [
        {
            path: `Cohort`,
            type: 'cohort',
            href: urls.cohort('new'),
        },
    ],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}

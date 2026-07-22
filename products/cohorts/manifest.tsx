import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Cohorts',
    scenes: {
        CohortsStaffTools: {
            import: () => import('./frontend/staff/CohortsStaffToolsScene'),
            instanceLevel: true,
            name: 'Cohorts staff tools',
        },
    },
    routes: {
        '/feature_flags/staff/cohorts': ['CohortsStaffTools', 'cohortsStaffTools'],
    },
    urls: {
        cohort: (id: string | number): string => `/cohorts/${id}`,
        cohorts: (): string => '/cohorts',
        cohortCalculationHistory: (id: string | number): string => `/cohorts/${id}/calculation-history`,
        cohortsStaffTools: (cohortId?: number): string =>
            `/feature_flags/staff/cohorts${cohortId ? `?cohort_id=${cohortId}` : ''}`,
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
            sceneKeys: ['Cohorts', 'Cohort'],
        },
    ],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}

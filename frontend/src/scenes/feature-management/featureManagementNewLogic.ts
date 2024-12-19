import { connect, kea, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, Feature } from '~/types'

import type { featureManagementNewLogicType } from './featureManagementNewLogicType'

const NEW_FEATURE: Omit<Feature, 'primary_early_access_feature_id' | 'documentation_url' | 'issue_url'> = {
    id: null,
    key: '',
    name: '',
    description: '',
    deleted: false,
    archived: false,
    created_at: null,
    created_by: null,
}

export const featureManagementNewLogic = kea<featureManagementNewLogicType>([
    props({}),
    path(['scenes', 'features', 'featureManagementNewLogic']),
    connect({}),
    forms(({ actions }) => ({
        feature: {
            defaults: { ...NEW_FEATURE },
            submit: (feature) => {
                actions.createFeature(feature)
            },
        },
    })),
    reducers({}),
    loaders(() => ({
        feature: {
            loadFeature: () => {
                return NEW_FEATURE
            },
            createFeature: (updatedFeature: Partial<Feature>) => {
                // eslint-disable-next-line no-console
                console.log('Create feature', updatedFeature)
                return NEW_FEATURE
            },
        },
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: Scene.FeatureManagement,
                        name: 'Features',
                        path: urls.featureManagement(),
                    },
                    {
                        key: Scene.FeatureManagementNew,
                        name: 'New feature',
                        path: urls.featureManagementNew(),
                    },
                ]

                return breadcrumbs
            },
        ],
    }),
])

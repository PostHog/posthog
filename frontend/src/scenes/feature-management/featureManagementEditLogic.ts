import { lemonToast } from '@posthog/lemon-ui'
import { connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, FeatureType } from '~/types'

import type { featureManagementEditLogicType } from './featureManagementEditLogicType'
import { featureManagementLogic } from './featureManagementLogic'

export interface FeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export type NewFeatureForm = Pick<FeatureType, 'key' | 'name' | 'description'>

const NEW_FEATURE: NewFeatureForm = {
    key: '',
    name: '',
    description: '',
}

export const featureManagementEditLogic = kea<featureManagementEditLogicType>([
    props({} as FeatureLogicProps),
    path(['scenes', 'features', 'featureManagementNewLogic']),
    connect({
        actions: [featureManagementLogic, ['loadFeatures']],
    }),
    loaders(({ props, actions }) => ({
        feature: {
            saveFeature: async (updatedFeature: NewFeatureForm | FeatureType) => {
                let feature
                if (props.id === 'new') {
                    feature = await api.features.create(updatedFeature)
                } else {
                    feature = await api.features.update(updatedFeature as FeatureType)
                }

                // Reset the form after creation
                actions.resetFeature()
                return feature
            },
        },
    })),
    forms(({ actions }) => ({
        feature: {
            defaults: { ...NEW_FEATURE },
            // sync validation, will be shown as errors in the form
            errors: ({ name }) => {
                if (!name) {
                    return { name: 'Name is required' }
                }
                return {}
            },
            submit: (feature) => {
                actions.saveFeature(feature)
            },
        },
    })),
    reducers({
        feature: [
            NEW_FEATURE,
            {
                setFeatureValue: (state, { name, value }) => {
                    const updatedField = typeof name === 'object' ? name[0] : name
                    const feature = { ...state, [updatedField]: value }

                    if (updatedField === 'name') {
                        // Set the key to a slugified version of the name
                        feature.key = feature.name.toLowerCase().replace(/[^a-z0-9_]/g, '-')
                    }

                    return feature
                },
            },
        ],
    }),
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
    listeners(({ actions }) => ({
        saveFeatureSuccess: ({ feature }) => {
            lemonToast.success(`Feature ${feature.name} saved`)
            actions.loadFeatures()
            feature.id && router.actions.replace(urls.featureManagement(feature.id))
        },
    })),
])

import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureTabs,
    EarlyAccessFeatureType,
    NewEarlyAccessFeatureType,
} from '~/types'

import type { earlyAccessFeatureLogicType } from './earlyAccessFeatureLogicType'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

export const NEW_EARLY_ACCESS_FEATURE: NewEarlyAccessFeatureType = {
    name: '',
    description: '',
    stage: EarlyAccessFeatureStage.Draft,
    documentation_url: '',
    feature_flag_id: undefined,
}

export interface EarlyAccessFeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const earlyAccessFeatureLogic = kea<earlyAccessFeatureLogicType>([
    path(['scenes', 'features', 'featureLogic']),
    props({} as EarlyAccessFeatureLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], earlyAccessFeaturesLogic, ['earlyAccessFeatures']],
        actions: [earlyAccessFeaturesLogic, ['loadEarlyAccessFeatures', 'loadEarlyAccessFeaturesSuccess']],
    })),
    actions({
        setEarlyAccessFeatureMissing: true,
        toggleImplementOptInInstructionsModal: true,
        editFeature: (editing: boolean) => ({ editing }),
        updateStage: (stage: EarlyAccessFeatureStage) => ({ stage }),
        deleteEarlyAccessFeature: (earlyAccessFeatureId: EarlyAccessFeatureType['id']) => ({ earlyAccessFeatureId }),
        setActiveTab: (activeTab: EarlyAccessFeatureTabs) => ({ activeTab }),
    }),
    loaders(({ props, actions }) => ({
        earlyAccessFeature: {
            loadEarlyAccessFeature: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const response = await api.earlyAccessFeatures.get(props.id)
                        return response
                    } catch (error: any) {
                        actions.setEarlyAccessFeatureMissing()
                        throw error
                    }
                }
                return NEW_EARLY_ACCESS_FEATURE
            },
            saveEarlyAccessFeature: async (
                updatedEarlyAccessFeature: Partial<EarlyAccessFeatureType | NewEarlyAccessFeatureType>
            ) => {
                let result: EarlyAccessFeatureType
                if (props.id === 'new') {
                    result = await api.earlyAccessFeatures.create(
                        updatedEarlyAccessFeature as NewEarlyAccessFeatureType
                    )
                    router.actions.replace(urls.earlyAccessFeature(result.id))
                } else {
                    result = await api.earlyAccessFeatures.update(
                        props.id,
                        updatedEarlyAccessFeature as EarlyAccessFeatureType
                    )
                }
                return result
            },
        },
    })),
    forms(({ actions }) => ({
        earlyAccessFeature: {
            defaults: { ...NEW_EARLY_ACCESS_FEATURE } as NewEarlyAccessFeatureType | EarlyAccessFeatureType,
            errors: (payload) => ({
                name: !payload.name ? 'Feature name must be set' : undefined,
            }),
            submit: async (payload) => {
                actions.saveEarlyAccessFeature(payload)
            },
        },
    })),
    reducers({
        earlyAccessFeatureMissing: [
            false,
            {
                setEarlyAccessFeatureMissing: () => true,
            },
        ],
        isEditingFeature: [
            false,
            {
                editFeature: (_, { editing }) => editing,
            },
        ],
        implementOptInInstructionsModal: [
            false,
            {
                toggleImplementOptInInstructionsModal: (state) => !state,
            },
        ],
        activeTab: [
            EarlyAccessFeatureTabs.OptedIn as EarlyAccessFeatureTabs,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.earlyAccessFeature],
            (earlyAccessFeature: EarlyAccessFeatureType): Breadcrumb[] => [
                {
                    key: Scene.EarlyAccessFeatures,
                    name: 'Early Access Management',
                    path: urls.earlyAccessFeatures(),
                },
                {
                    key: [Scene.EarlyAccessFeature, earlyAccessFeature.id || 'new'],
                    name: earlyAccessFeature.name,
                },
            ],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        updateStage: async ({ stage }) => {
            'id' in values.earlyAccessFeature &&
                (await api.earlyAccessFeatures.update(props.id, {
                    ...values.earlyAccessFeature,
                    stage: stage,
                }))
            actions.loadEarlyAccessFeature()
            actions.loadEarlyAccessFeatures()
        },
        saveEarlyAccessFeatureSuccess: ({ earlyAccessFeature }) => {
            lemonToast.success('Early Access Feature saved')
            actions.loadEarlyAccessFeatures()
            earlyAccessFeature.id && router.actions.replace(urls.earlyAccessFeature(earlyAccessFeature.id))
            actions.editFeature(false)
        },
        deleteEarlyAccessFeature: async ({ earlyAccessFeatureId }) => {
            try {
                await api.earlyAccessFeatures.delete(earlyAccessFeatureId)
                lemonToast.info(
                    'Early access feature deleted. Remember to delete corresponding feature flag if necessary'
                )
                actions.loadEarlyAccessFeaturesSuccess(
                    values.earlyAccessFeatures.filter((feature) => feature.id !== earlyAccessFeatureId)
                )
                router.actions.push(urls.earlyAccessFeatures())
            } catch (e) {
                lemonToast.error(`Error deleting Early Access Feature: ${e}`)
            }
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.earlyAccessFeature(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadEarlyAccessFeature()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadEarlyAccessFeature()
        }
    }),
])

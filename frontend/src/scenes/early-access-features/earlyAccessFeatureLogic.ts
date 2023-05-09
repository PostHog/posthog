import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { Breadcrumb, EarlyAccessFeatureStage, EarlyAccsesFeatureType, NewEarlyAccessFeatureType } from '~/types'
import type { earlyAccessFeatureLogicType } from './earlyAccessFeatureLogicType'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { lemonToast } from '@posthog/lemon-ui'

const NEW_EARLY_ACCESS_FEATURE: NewEarlyAccessFeatureType = {
    name: '',
    description: '',
    stage: EarlyAccessFeatureStage.Beta,
    documentation_url: '',
    feature_flag_id: undefined,
}

export interface FeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const earlyAccessFeatureLogic = kea<earlyAccessFeatureLogicType>([
    path(['scenes', 'features', 'featureLogic']),
    props({} as FeatureLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [earlyAccessFeaturesLogic, ['loadEarlyAccessFeatures']],
    })),
    actions({
        toggleImplementOptInInstructionsModal: true,
        cancel: true,
        editFeature: (editing: boolean) => ({ editing }),
        promote: true,
        deleteEarlyAccessFeature: (earlyAccessFeature: Partial<EarlyAccsesFeatureType>) => ({ earlyAccessFeature }),
    }),
    loaders(({ props }) => ({
        earlyAccessFeature: {
            loadEarlyAccessFeature: async () => {
                if (props.id && props.id !== 'new') {
                    const response = await api.earlyAccessFeatures.get(props.id)
                    return response
                }
                return NEW_EARLY_ACCESS_FEATURE
            },
            saveEarlyAccessFeature: async (updatedEarlyAccessFeature: Partial<EarlyAccsesFeatureType>) => {
                let result: EarlyAccsesFeatureType
                if (props.id === 'new') {
                    result = await api.earlyAccessFeatures.create(
                        updatedEarlyAccessFeature as NewEarlyAccessFeatureType
                    )
                    router.actions.push(urls.earlyAccessFeature(result.id))
                } else {
                    result = await api.earlyAccessFeatures.update(
                        props.id,
                        updatedEarlyAccessFeature as EarlyAccsesFeatureType
                    )
                }
                return result
            },
        },
    })),
    forms(({ actions }) => ({
        earlyAccessFeature: {
            defaults: { ...NEW_EARLY_ACCESS_FEATURE } as NewEarlyAccessFeatureType | EarlyAccsesFeatureType,
            errors: (payload) => ({
                name: !payload.name ? 'Feature name must be set' : undefined,
            }),
            submit: async (payload) => {
                actions.saveEarlyAccessFeature(payload)
            },
        },
    })),
    reducers({
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
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.earlyAccessFeature],
            (earlyAccessFeature: EarlyAccsesFeatureType): Breadcrumb[] => [
                {
                    name: 'Early Access Features',
                    path: urls.earlyAccessFeatures(),
                },
                ...(earlyAccessFeature?.name ? [{ name: earlyAccessFeature.name }] : []),
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        cancel: () => {
            if (!('id' in values.earlyAccessFeature)) {
                actions.resetEarlyAccessFeature()
                router.actions.push(urls.earlyAccessFeatures())
            }
            actions.editFeature(false)
        },
        promote: async () => {
            'id' in values.earlyAccessFeature && (await api.earlyAccessFeatures.promote(values.earlyAccessFeature.id))
            actions.loadEarlyAccessFeature()
            actions.loadEarlyAccessFeatures()
        },
        deleteEarlyAccessFeature: async ({ earlyAccessFeature }) => {
            deleteWithUndo({
                endpoint: `projects/${values.currentTeamId}/early_access_feature`,
                object: { name: earlyAccessFeature.name, id: earlyAccessFeature.id },
                callback: () => {
                    earlyAccessFeature.id &&
                        earlyAccessFeaturesLogic
                            .findMounted()
                            ?.actions.deleteEarlyAccessFeatureById(earlyAccessFeature.id)
                    earlyAccessFeaturesLogic.findMounted()?.actions.loadEarlyAccessFeatures()
                    router.actions.push(urls.earlyAccessFeatures())
                },
            })
        },
        saveEarlyAccessFeatureSuccess: ({ earlyAccessFeature }) => {
            lemonToast.success('Early Access Feature saved')
            actions.loadEarlyAccessFeatures()
            earlyAccessFeature.id && router.actions.replace(urls.earlyAccessFeature(earlyAccessFeature.id))
            actions.editFeature(false)
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.earlyAccessFeature(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadEarlyAccessFeature()
                } else {
                    actions.resetEarlyAccessFeature()
                }
            }
        },
    })),
    afterMount(async ({ props, actions }) => {
        if (props.id !== 'new') {
            await actions.loadEarlyAccessFeature()
        }
        if (props.id === 'new') {
            actions.resetEarlyAccessFeature()
            actions.editFeature
        }
    }),
])

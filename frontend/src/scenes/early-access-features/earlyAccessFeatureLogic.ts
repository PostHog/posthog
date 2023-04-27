import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { EarlyAccsesFeatureType, NewEarlyAccessFeatureType } from '~/types'
import type { earlyAccessFeatureLogicType } from './earlyAccessFeatureLogicType'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

const NEW_EARLY_ACCESS_FEATURE: NewEarlyAccessFeatureType = {
    name: '',
    description: '',
    stage: 'alpha',
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
        actions: [earlyAccessFeaturesLogic, ['loadEarlyAccessFeatures']],
    })),
    actions({
        toggleImplementOptInInstructionsModal: true,
        cancel: true,
        editFeature: (editing: boolean) => ({ editing }),
    }),
    loaders(({ props }) => ({
        earlyAccessFeature: {
            loadEarlyAccessFeature: async () => {
                const response = await api.earlyAccessFeatures.get(props.id)
                return response
            },
        },
    })),
    forms(({ props, actions }) => ({
        earlyAccessFeature: {
            defaults: { ...NEW_EARLY_ACCESS_FEATURE } as NewEarlyAccessFeatureType | EarlyAccsesFeatureType,
            errors: (payload) => ({
                name: !payload.name ? 'Feature name must be set' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                await breakpoint()
                if (props.id === 'new') {
                    const result = await api.earlyAccessFeatures.create(payload as NewEarlyAccessFeatureType)
                    router.actions.push(urls.earlyAccessFeature(result.id))
                } else {
                    await api.earlyAccessFeatures.update(props.id, payload as EarlyAccsesFeatureType)
                }

                actions.resetEarlyAccessFeature()
                actions.loadEarlyAccessFeatures()
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
    }),
    listeners(({ actions, values }) => ({
        cancel: () => {
            if ('id' in values.earlyAccessFeature) {
                actions.editFeature(false)
            } else {
                actions.resetEarlyAccessFeature()
                router.actions.push(urls.earlyAccessFeatures())
            }
        },
    })),
    afterMount(async ({ props, actions }) => {
        if (props.id !== 'new') {
            await actions.loadEarlyAccessFeature()
        }

        actions.editFeature(props.id === 'new')
    }),
])

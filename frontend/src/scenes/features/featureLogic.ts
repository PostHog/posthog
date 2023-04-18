import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { FeatureType, NewFeatureType } from '~/types'
import type { featureLogicType } from './featureLogicType'

const NEW_FEATURE: NewFeatureType = {
    name: '',
    description: '',
    stage: 'alpha',
    image_url: '',
    documentation_url: '',
    feature_flag_id: undefined,
}

export interface FeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const featureLogic = kea<featureLogicType>([
    path(['scenes', 'features', 'featureLogic']),
    props({} as FeatureLogicProps),
    key(({ id }) => id),
    actions({
        cancel: true,
        editFeature: (editing: boolean) => ({ editing }),
    }),
    loaders(({ props }) => ({
        feature: {
            loadFeature: async () => {
                const response = await api.features.get(props.id)
                return response
            },
        },
    })),
    forms(({ props }) => ({
        feature: {
            defaults: { ...NEW_FEATURE } as NewFeatureType | FeatureType,
            errors: (payload) => ({
                name: !payload.name ? 'Feature name must be set' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                await breakpoint()
                if (props.id === 'new') {
                    const result = await api.features.create(payload as NewFeatureType)
                    router.actions.push(urls.feature(result.id))
                } else {
                    await api.features.update(props.id, payload as FeatureType)
                }
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
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
    }),
    listeners(({ actions, values }) => ({
        cancel: () => {
            if ('id' in values.feature) {
                actions.editFeature(false)
            } else {
                actions.resetFeature()
                router.actions.push(urls.features())
            }
        },
    })),
    afterMount(async ({ props, actions }) => {
        if (props.id !== 'new') {
            await actions.loadFeature()
        }

        actions.editFeature(props.id === 'new')
    }),
])

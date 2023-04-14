import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { urls } from 'scenes/urls'
import { FeatureType, NewFeatureType } from '~/types'
import type { featureLogicType } from './featureLogicType'

const NEW_FEATURE: NewFeatureType = {
    name: '',
    description: '',
    stage: 'alpha',
    image_url: '',
    documentation_url: '',
    feature_flag_key: '',
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
                name: !payload.name ? 'You need to set a name' : undefined,
                feature_flag_key:
                    'feature_flag_key' in payload ? validateFeatureFlagKey(payload.feature_flag_key) : undefined,
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
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
    }),
    listeners(({ actions }) => ({
        cancel: () => {
            actions.resetFeature()
            router.actions.push(urls.features())
        },
    })),
    afterMount(async ({ props, actions }) => {
        if (props.id !== 'new') {
            await actions.loadFeature()
        }
    }),
])

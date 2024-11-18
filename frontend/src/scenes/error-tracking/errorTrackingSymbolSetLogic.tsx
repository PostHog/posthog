import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingSymbolSetLogicType } from './errorTrackingSymbolSetLogicType'

export enum ErrorGroupTab {
    Overview = 'overview',
    Breakdowns = 'breakdowns',
}

export interface ErrorTrackingSymbolSet {
    ref: string
}

export const errorTrackingSymbolSetLogic = kea<errorTrackingSymbolSetLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSymbolSetLogic']),

    actions({
        setUploadSymbolSetReference: (ref: string | null) => ({ ref }),
    }),

    reducers({
        uploadSymbolSetReference: [
            null as string | null,
            {
                setUploadSymbolSetReference: (_, { ref }) => ref,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    name: 'Error tracking',
                    path: urls.errorTracking(),
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    name: 'Configuration',
                },
            ],
        ],
    }),

    loaders(() => ({
        missingSymbolSets: [
            [] as ErrorTrackingSymbolSet[],
            {
                loadMissingSymbolSets: async () => {
                    const response = await api.errorTracking.missingSymbolSets()
                    return response
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        uploadSymbolSet: {
            defaults: { files: [] } as { files: File[] },
            submit: async ({ files }) => {
                if (files.length > 0 && values.uploadSymbolSetReference) {
                    const formData = new FormData()
                    const file = files[0]
                    formData.append('source_map', file)
                    await api.errorTracking.updateSymbolSet(values.uploadSymbolSetReference, formData)
                    actions.setUploadSymbolSetReference(null)
                    actions.loadMissingSymbolSets()
                    lemonToast.success('Source map uploaded')
                }
            },
        },
    })),

    afterMount(({ actions }) => {
        actions.loadMissingSymbolSets()
    }),
])

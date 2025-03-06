import { lemonToast } from '@posthog/lemon-ui'
import { actions, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { ErrorTrackingSymbolSet } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingSymbolSetLogicType } from './errorTrackingSymbolSetLogicType'

export enum ErrorGroupTab {
    Overview = 'overview',
    Breakdowns = 'breakdowns',
}

export type SymbolSetUpload = SourceMapUpload

export interface SourceMapUpload {
    minified: File
    sourceMap: File
}

export const errorTrackingSymbolSetLogic = kea<errorTrackingSymbolSetLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSymbolSetLogic']),

    actions({
        setUploadSymbolSetId: (id: ErrorTrackingSymbolSet['id'] | null) => ({ id }),
    }),

    reducers({
        uploadSymbolSetId: [
            null as string | null,
            {
                setUploadSymbolSetId: (_, { id }) => id,
            },
        ],
    }),

    loaders(({ values }) => ({
        symbolSets: [
            [] as ErrorTrackingSymbolSet[],
            {
                loadSymbolSets: async () => {
                    const response = await api.errorTracking.symbolSets()
                    return response.results
                },
                deleteSymbolSet: async (id) => {
                    await api.errorTracking.deleteSymbolSet(id)
                    const newValues = [...values.symbolSets]
                    return newValues.filter((v) => v.id !== id)
                },
            },
        ],
    })),

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
        validSymbolSets: [(s) => [s.symbolSets], (symbolSets) => symbolSets.filter((s) => !!s.storage_ptr)],
        missingSymbolSets: [(s) => [s.symbolSets], (symbolSets) => symbolSets.filter((s) => !s.storage_ptr)],
    }),

    forms(({ values, actions }) => ({
        uploadSymbolSet: {
            defaults: { minified: [], sourceMap: [] } as { minified: File[]; sourceMap: File[] },
            submit: async ({ minified, sourceMap }) => {
                if (minified.length < 1 || sourceMap.length < 1) {
                    lemonToast.error('Please select both a minified file and a source map file')
                    return
                }

                const minifiedSrc = minified[0]
                const sourceMapSrc = sourceMap[0]
                const id = values.uploadSymbolSetId

                if (id == null) {
                    return
                }

                const formData = new FormData()
                formData.append('minified', minifiedSrc)
                formData.append('source_map', sourceMapSrc)
                await api.errorTracking.updateSymbolSet(id, formData)
                actions.setUploadSymbolSetId(null)
                actions.loadSymbolSets()
                actions.resetUploadSymbolSet()
                lemonToast.success('Source map uploaded')
            },
        },
    })),
])

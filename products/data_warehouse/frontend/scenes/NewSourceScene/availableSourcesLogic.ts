import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { SourceConfig } from '~/queries/schema/schema-general'

import type { availableSourcesLogicType } from './availableSourcesLogicType'

export const availableSourcesLogic = kea<availableSourcesLogicType>([
    path(['products', 'dataWarehouse', 'availableSourcesLogic']),
    loaders({
        availableSources: [
            null as Record<string, SourceConfig> | null,
            {
                load: async () => {
                    try {
                        return await api.externalDataSources.wizard()
                    } catch (e: any) {
                        if (e.status === 403) {
                            return null
                        }
                        throw e
                    }
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.load()
    }),
])

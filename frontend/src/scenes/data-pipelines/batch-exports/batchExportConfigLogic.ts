// Lightweight logic that loads and caches a batch export's configuration.
// Child logics (runs, backfills, modal) connect here instead of the heavyweight form logic,
// so they can be mounted independently (e.g. from the hog function backfills tab).
import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { BatchExportConfiguration } from '~/types'

import type { batchExportConfigLogicType } from './batchExportConfigLogicType'

export interface BatchExportConfigLogicProps {
    id: string | null
}

export const batchExportConfigLogic = kea<batchExportConfigLogicType>([
    props({} as BatchExportConfigLogicProps),
    key(({ id }) => id ?? 'new'),
    path((key) => ['scenes', 'data-pipelines', 'batch-exports', 'batchExportConfigLogic', key]),
    loaders(({ props }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    if (props.id) {
                        return await api.batchExports.get(props.id)
                    }
                    return null
                },
                setBatchExportConfig: (config: BatchExportConfiguration) => config,
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadBatchExportConfig()
    }),
])

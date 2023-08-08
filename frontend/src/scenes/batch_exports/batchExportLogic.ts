import { kea, key, path, props } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration } from '~/types'

import api from 'lib/api'

import type { batchExportLogicType } from './batchExportLogicType'

export type BatchExportLogicProps = {
    id: string
}

export const batchExportLogic = kea<batchExportLogicType>([
    props({} as BatchExportLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportLogic', key]),

    loaders(({ props }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    if (props.id === 'new') {
                        return null
                    }
                    const res = await api.batchExports.get(props.id)
                    return res
                },
            },
        ],
    })),
])

import { connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { RawBatchExportBackfill } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import type { batchExportBackfillsLogicType } from './batchExportBackfillsLogicType'
import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'

export interface BatchExportBackfillsLogicProps {
    id: string
}

export const batchExportBackfillsLogic = kea<batchExportBackfillsLogicType>([
    props({} as BatchExportBackfillsLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'batchExportBackfillsLogic', key]),
    connect((props: BatchExportBackfillsLogicProps) => ({
        values: [
            teamLogic(),
            ['currentTeamId'],
            pipelineBatchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig'],
        ],
        actions: [batchExportBackfillModalLogic(props), ['submitBackfillFormSuccess', 'openBackfillModal']],
    })),
    loaders(({ props, values }) => ({
        backfillsPaginatedResponse: [
            null as PaginatedResponse<RawBatchExportBackfill> | null,
            {
                loadBackfills: async () => {
                    return await api.batchExports.listBackfills(props.id, {
                        ordering: '-created_at',
                    })
                },
                loadOlderBackfills: async () => {
                    const nextUrl = values.backfillsPaginatedResponse?.next

                    if (!nextUrl) {
                        return values.backfillsPaginatedResponse
                    }
                    const res = await api.get<PaginatedResponse<RawBatchExportBackfill>>(nextUrl)
                    res.results = [...(values.backfillsPaginatedResponse?.results ?? []), ...res.results]

                    return res
                },
            },
        ],
    })),
])

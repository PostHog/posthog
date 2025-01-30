import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { BatchExportBackfill, RawBatchExportBackfill } from '~/types'

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
    actions({
        loadBackfills: true,
        cancelBackfill: (backfill: BatchExportBackfill) => ({ backfill }),
    }),
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
    selectors({
        hasMoreBackfillsToLoad: [
            (s) => [s.backfillsPaginatedResponse],
            (backfillsPaginatedResponse) => !!backfillsPaginatedResponse?.next,
        ],
        loading: [
            (s) => [s.backfillsPaginatedResponseLoading],
            (backfillsPaginatedResponseLoading) => backfillsPaginatedResponseLoading,
        ],
        latestBackfills: [
            (s) => [s.backfillsPaginatedResponse],
            (backfillsPaginatedResponse): BatchExportBackfill[] => {
                const backfills = backfillsPaginatedResponse?.results ?? []
                return backfills.map((backfill) => {
                    return {
                        ...backfill,
                        created_at: dayjs(backfill.created_at),
                        finished_at: backfill.finished_at ? dayjs(backfill.finished_at) : undefined,
                        start_at: backfill.start_at ? dayjs(backfill.start_at) : undefined,
                        end_at: backfill.end_at ? dayjs(backfill.end_at) : undefined,
                        last_updated_at: backfill.last_updated_at ? dayjs(backfill.last_updated_at) : undefined,
                    }
                })
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        cancelBackfill: async ({ backfill }) => {
            // TODO
            // await api.batchExports.cancelBackfill(props.id, backfill.id)
            // lemonToast.success('Backfill has been cancelled.')
            console.log('cancelBackfill not yet implemented ;(')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBackfills()
    }),
])

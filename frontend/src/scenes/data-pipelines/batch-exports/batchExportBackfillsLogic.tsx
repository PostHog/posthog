import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { BatchExportBackfill, RawBatchExportBackfill } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import type { batchExportBackfillsLogicType } from './batchExportBackfillsLogicType'
import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'

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
            batchExportConfigurationLogic({
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
                    try {
                        return await api.batchExports.listBackfills(props.id, {
                            ordering: '-created_at',
                        })
                    } catch (e) {
                        lemonToast.error('Unknown error occurred when fetching backfills')
                        throw e
                    }
                },
                loadOlderBackfills: async () => {
                    const nextUrl = values.backfillsPaginatedResponse?.next

                    if (!nextUrl) {
                        return values.backfillsPaginatedResponse
                    }
                    try {
                        const res = await api.get<PaginatedResponse<RawBatchExportBackfill>>(nextUrl)
                        res.results = [...(values.backfillsPaginatedResponse?.results ?? []), ...res.results]

                        return res
                    } catch (e) {
                        lemonToast.error('Unknown error occurred when fetching backfills')
                        throw e
                    }
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
                    const parseDateSafely = (date: string | null | undefined): dayjs.Dayjs | undefined => {
                        if (!date) {
                            return undefined
                        }
                        const parsed = dayjs(date)
                        return parsed.isValid() ? parsed : undefined
                    }
                    return {
                        ...backfill,
                        created_at: parseDateSafely(backfill.created_at),
                        finished_at: parseDateSafely(backfill.finished_at),
                        start_at: parseDateSafely(backfill.start_at),
                        end_at: parseDateSafely(backfill.end_at),
                        last_updated_at: parseDateSafely(backfill.last_updated_at),
                    }
                })
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        cancelBackfill: async ({ backfill }) => {
            try {
                await api.batchExports.cancelBackfill(props.id, backfill.id)
                lemonToast.success('Backfill has been cancelled.')
                actions.loadBackfills()
            } catch {
                lemonToast.error('Failed to cancel backfill. Please try again.')
            }
        },
        submitBackfillFormSuccess: () => {
            setTimeout(() => {
                actions.loadBackfills()
            }, 1000)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBackfills()
    }),
])

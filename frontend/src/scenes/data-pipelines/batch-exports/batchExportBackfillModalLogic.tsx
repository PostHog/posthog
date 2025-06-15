import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { batchExportBackfillModalLogicType } from './batchExportBackfillModalLogicType'
import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'

export interface BatchExportBackfillModalLogicProps {
    id: string
}

export const batchExportBackfillModalLogic = kea<batchExportBackfillModalLogicType>([
    props({} as BatchExportBackfillModalLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'batchExportBackfillModalLogic', key]),
    connect((props: BatchExportBackfillModalLogicProps) => ({
        values: [
            batchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig'],
        ],
    })),
    actions({
        openBackfillModal: true,
        closeBackfillModal: true,
        setEarliestBackfill: true,
        unsetEarliestBackfill: true,
    }),
    reducers({
        isBackfillModalOpen: [
            false,
            {
                openBackfillModal: () => true,
                closeBackfillModal: () => false,
            },
        ],
        isEarliestBackfill: [
            false,
            {
                setEarliestBackfill: () => true,
                unsetEarliestBackfill: () => false,
            },
        ],
    }),
    forms(({ props, actions, values }) => ({
        backfillForm: {
            defaults: {
                start_at: undefined,
                end_at: dayjs().tz(teamLogic.values.timezone).hour(0).minute(0).second(0).millisecond(0),
                earliest_backfill: false,
            } as {
                start_at?: Dayjs
                end_at?: Dayjs
                earliest_backfill: boolean
            },

            errors: ({ start_at, end_at, earliest_backfill }) => ({
                start_at: !start_at ? (!earliest_backfill ? 'Start date is required' : undefined) : undefined,
                end_at: !end_at ? 'End date is required' : undefined,
                earliest_backfill: undefined,
            }),

            submit: async ({ start_at, end_at, earliest_backfill }) => {
                if (values.batchExportConfig && values.batchExportConfig.interval.endsWith('minutes')) {
                    // TODO: Make this generic for all minute frequencies.
                    // Currently, only 5 minute batch exports are supported.
                    if (
                        (start_at?.minute() !== undefined && !(start_at?.minute() % 5 === 0)) ||
                        (end_at?.minute() !== undefined && !(end_at?.minute() % 5 === 0))
                    ) {
                        lemonToast.error(
                            'Backfilling a 5 minute batch export requires bounds be multiple of five minutes'
                        )
                        return
                    }
                }

                let upperBound = dayjs().tz(teamLogic.values.timezone)
                let period = '1 hour'

                if (values.batchExportConfig && end_at) {
                    if (values.batchExportConfig.interval == 'hour') {
                        upperBound = upperBound.add(1, 'hour')
                    } else if (values.batchExportConfig.interval == 'day') {
                        upperBound = upperBound.hour(0).minute(0).second(0)
                        upperBound = upperBound.add(1, 'day')
                        period = '1 day'
                    } else if (values.batchExportConfig.interval.endsWith('minutes')) {
                        // TODO: Make this generic for all minute frequencies.
                        // Currently, only 5 minute batch exports are supported.
                        upperBound = upperBound.add(5, 'minute')
                        period = '5 minutes'
                    } else {
                        upperBound = upperBound.add(1, 'hour')
                    }

                    if (end_at > upperBound) {
                        lemonToast.error(
                            `Requested backfill end date lies too far into the future. Use an end date that is no more than ${period} from now (in your project's timezone)`
                        )
                        return
                    }
                }

                await api.batchExports
                    .createBackfill(props.id, {
                        start_at: earliest_backfill ? null : start_at?.toISOString() ?? null,
                        end_at: end_at?.toISOString() ?? null,
                    })
                    .catch((e) => {
                        if (e.detail) {
                            actions.setBackfillFormManualErrors({
                                [e.attr ?? 'start_at']: e.detail,
                            })
                        } else {
                            lemonToast.error('Unknown error occurred')
                        }

                        throw e
                    })

                actions.closeBackfillModal()
                return
            },
        },
    })),
])

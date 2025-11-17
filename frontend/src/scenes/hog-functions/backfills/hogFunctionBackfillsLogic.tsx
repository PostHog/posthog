import { actions, connect, kea, key, listeners, path, props } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { batchExportConfigurationLogic } from 'scenes/data-pipelines/batch-exports/batchExportConfigurationLogic'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import type { hogFunctionBackfillsLogicType } from './hogFunctionBackfillsLogicType'

export interface HogFunctionBackfillsLogicProps {
    id: string
}

export const hogFunctionBackfillsLogic = kea<hogFunctionBackfillsLogicType>([
    props({} as HogFunctionBackfillsLogicProps),
    key(({ id }: HogFunctionBackfillsLogicProps) => id),
    path((key) => ['scenes', 'pipeline', 'hogFunctionBackfillsLogic', key]),
    connect((props) => ({
        values: [
            hogFunctionConfigurationLogic(props),
            ['configuration', 'type', 'loading', 'loaded', 'teamHasCohortFilters', 'currentProjectId'],
            batchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig', 'batchExportConfigLoading'],
        ],
        actions: [
            batchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['loadBatchExportConfig'],
        ],
    })),
    actions({
        enableHogFunctionBackfills: () => true,
    }),
    listeners(({ actions, values, props }) => ({
        enableHogFunctionBackfills: async () => {
            const batchExportConfig = {
                id: props.id,
                paused: true,
                name: values.configuration.name,
                interval: 'once' as const,
                model: 'events',
                filters: values.configuration.filters,
                destination: {
                    type: 'RealtimeDestinationBackfill' as const,
                },
            }

            await api.batchExports.create(batchExportConfig)
            lemonToast.success('Backfills enabled for this destination.')

            // Reload page to get the updated config and render <BatchExportBackfills />
            await actions.loadBatchExportConfig()
        },
    })),
])

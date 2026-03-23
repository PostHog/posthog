import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { HogFunctionConfigurationType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import type { hogFunctionBackfillsLogicType } from './hogFunctionBackfillsLogicType'

export interface HogFunctionBackfillsLogicProps {
    id: string
}

export const hogFunctionBackfillsLogic = kea<hogFunctionBackfillsLogicType>([
    props({} as HogFunctionBackfillsLogicProps),
    key(({ id }: HogFunctionBackfillsLogicProps) => id),
    path((key) => ['scenes', 'pipeline', 'hogFunctionBackfillsLogic', key]),
    connect((props: HogFunctionBackfillsLogicProps) => ({
        values: [hogFunctionConfigurationLogic(props), ['configuration']],
        actions: [
            hogFunctionConfigurationLogic(props),
            ['setConfigurationValues', 'loadHogFunction', 'loadHogFunctionSuccess'],
        ],
    })),
    actions({
        enableHogFunctionBackfills: () => true,
        setLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        isLoading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
    }),
    selectors({
        isReady: [
            (s) => [s.configuration, s.isLoading],
            (configuration: HogFunctionConfigurationType, isLoading: boolean) => {
                return !!configuration.batch_export_id && !isLoading
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        enableHogFunctionBackfills: async () => {
            try {
                actions.setLoading(true)
                await api.hogFunctions.enableBackfills(props.id)

                // Reload to get the updated config and render <BatchExportBackfills />
                actions.loadHogFunction()

                lemonToast.success('Backfills enabled for this destination.')
            } catch {
                lemonToast.error('Failed to enable backfills for this destination.')
            } finally {
                actions.setLoading(false)
            }
        },
        loadHogFunctionSuccess: () => {
            // Only enable backfills after the config has loaded and we know
            // batch_export_id is genuinely missing (not just not-yet-loaded).
            if (!values.configuration.batch_export_id) {
                actions.enableHogFunctionBackfills()
            }
        },
    })),
])

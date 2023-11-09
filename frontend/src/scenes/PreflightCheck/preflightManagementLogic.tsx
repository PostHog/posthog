import { connect, kea, listeners, path } from 'kea'
import { PreflightStatus } from '~/types'
import { preflightLogic } from './preflightLogic'
import api from 'lib/api'

/**
 * This logic explicitly handles api calls to the preflight endpoint.
 * We don't include in the preflightLogic as that logic is imported everywhere which can lead to circular dependencies.
 */
export const preflightManagementLogic = kea([
    path(['scenes', 'PreflightCheck', 'preflightManagementLogic']),
    connect({
        values: [preflightLogic, 'preflight', 'preflightLoading'],
        actions: [preflightLogic, 'setPreflight', 'loadPreflight'],
    }),
    listeners(({ actions }) => ({
        loadPreflight: async () => {
            const response = (await api.get('_preflight/')) as PreflightStatus
            actions.setPreflight(response)
        },
    })),
])

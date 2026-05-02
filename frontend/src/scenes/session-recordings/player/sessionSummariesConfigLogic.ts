import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { SessionSummariesConfig } from 'products/session_summaries/frontend/types'

import type { sessionSummariesConfigLogicType } from './sessionSummariesConfigLogicType'

export type SessionSummariesConfigForm = {
    product_context: string
}

export const sessionSummariesConfigLogic = kea<sessionSummariesConfigLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sessionSummariesConfigLogic']),

    actions({
        revertConfigForm: true,
    }),

    reducers({
        isLoading: [
            false,
            {
                loadConfig: () => true,
                loadConfigSuccess: () => false,
                loadConfigFailure: () => false,
            },
        ],
        isUpdating: [
            false,
            {
                updateConfig: () => true,
                updateConfigSuccess: () => false,
                updateConfigFailure: () => false,
            },
        ],
    }),

    loaders(() => ({
        config: {
            __default: null as SessionSummariesConfig | null,
            loadConfig: async (): Promise<SessionSummariesConfig> => {
                return await api.sessionSummaries.config.get()
            },
            updateConfig: async (data: SessionSummariesConfigForm): Promise<SessionSummariesConfig> => {
                const response = await api.sessionSummaries.config.update(data)
                lemonToast.success('Product context saved.')
                return response
            },
        },
    })),

    forms(({ actions }) => ({
        configForm: {
            defaults: { product_context: '' } as SessionSummariesConfigForm,
            submit: (values) => {
                actions.updateConfig(values)
            },
        },
    })),

    listeners(({ actions, values }) => ({
        loadConfigSuccess: ({ config }) => {
            if (config) {
                actions.setConfigFormValue('product_context', config.product_context ?? '')
            }
        },
        revertConfigForm: () => {
            actions.setConfigFormValue('product_context', values.config?.product_context ?? '')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfig()
    }),
])

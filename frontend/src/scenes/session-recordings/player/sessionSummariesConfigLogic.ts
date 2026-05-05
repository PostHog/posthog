import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { SessionSummariesConfig } from 'products/session_summaries/frontend/types'

import type { sessionSummariesConfigLogicType } from './sessionSummariesConfigLogicType'

export const CUSTOM_TAGS_MAX_COUNT = 15
export const CUSTOM_TAG_NAME_MAX_LENGTH = 60
export const CUSTOM_TAG_DESCRIPTION_MAX_LENGTH = 200
export const CUSTOM_TAG_NAME_REGEX = /^[a-z0-9_]{1,60}$/

export type CustomTagFormEntry = {
    name: string
    description: string
}

export type SessionSummariesConfigForm = {
    product_context: string
    custom_tags: CustomTagFormEntry[]
}

const customTagsToArray = (tags: Record<string, string> | null | undefined): CustomTagFormEntry[] => {
    if (!tags) {
        return []
    }
    return Object.entries(tags).map(([name, description]) => ({ name, description }))
}

const customTagsToDict = (tags: CustomTagFormEntry[]): Record<string, string> => {
    const dict: Record<string, string> = {}
    for (const { name, description } of tags) {
        const trimmedName = name.trim()
        if (trimmedName) {
            dict[trimmedName] = description.trim()
        }
    }
    return dict
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
                const response = await api.sessionSummaries.config.update({
                    product_context: data.product_context,
                    custom_tags: customTagsToDict(data.custom_tags),
                })
                lemonToast.success('Session summaries config saved.')
                return response
            },
        },
    })),

    forms(({ actions }) => ({
        configForm: {
            defaults: { product_context: '', custom_tags: [] } as SessionSummariesConfigForm,
            submit: (values) => {
                actions.updateConfig(values)
            },
        },
    })),

    listeners(({ actions, values }) => ({
        loadConfigSuccess: ({ config }) => {
            if (config) {
                actions.setConfigFormValues({
                    product_context: config.product_context ?? '',
                    custom_tags: customTagsToArray(config.custom_tags),
                })
            }
        },
        revertConfigForm: () => {
            actions.setConfigFormValues({
                product_context: values.config?.product_context ?? '',
                custom_tags: customTagsToArray(values.config?.custom_tags),
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfig()
    }),
])

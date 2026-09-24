import { MakeLogicType, afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'

import { notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookApi } from 'products/notebooks/frontend/generated/api.schemas'

const PRODUCT_ANALYTICS_HOME_NOTEBOOK_SHORT_ID = 'pa-home-v1'

export interface productAnalyticsHomeLogicValues {
    currentProjectId: number | null // projectLogic
    homeNotebook: NotebookApi | null
    homeNotebookError: string | null
    homeNotebookLoading: boolean
}

export interface productAnalyticsHomeLogicActions {
    loadHomeNotebook: () => void
    loadHomeNotebookSuccess: (homeNotebook: NotebookApi) => void
    loadHomeNotebookFailure: (error: string, errorObject?: unknown) => void
}

export type productAnalyticsHomeLogicType = MakeLogicType<
    productAnalyticsHomeLogicValues,
    productAnalyticsHomeLogicActions
>

export const productAnalyticsHomeLogic = kea<productAnalyticsHomeLogicType>([
    path(['scenes', 'saved-insights', 'productAnalyticsHomeLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        homeNotebook: [
            null as NotebookApi | null,
            {
                loadHomeNotebook: async () => {
                    if (values.currentProjectId === null) {
                        throw new Error('Project not found')
                    }
                    return await notebooksRetrieve(
                        String(values.currentProjectId),
                        PRODUCT_ANALYTICS_HOME_NOTEBOOK_SHORT_ID
                    )
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        posthog.capture('product analytics home viewed')
        actions.loadHomeNotebook()
    }),
])

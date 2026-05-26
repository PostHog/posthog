import { actions, afterMount, connect, isBreakpoint, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { accountsNotebooksList } from 'products/customer_analytics/frontend/generated/api'
import type { AccountNotebookApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountNotebooksLogicType } from './accountNotebooksLogicType'

export interface AccountNotebooksLogicProps {
    accountId: string
}

export const accountNotebooksLogic = kea<accountNotebooksLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountNotebooksLogic', key]),
    props({} as AccountNotebooksLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        refresh: true,
    }),
    loaders(({ props, values }) => ({
        notebooks: [
            null as AccountNotebookApi[] | null,
            {
                loadNotebooks: async (_ = null, breakpoint) => {
                    const projectId = String(values.currentTeamId)
                    try {
                        const response = await accountsNotebooksList(projectId, props.accountId)
                        breakpoint()
                        return response.results
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, {
                                scope: 'accountNotebooksLogic.loadNotebooks',
                            })
                            lemonToast.error('Failed to load account notebooks')
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadNotebooks()
    }),
])

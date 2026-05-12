import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DashboardVersionListItem } from '~/types'

import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'
import type { dashboardVersionHistoryLogicType } from './dashboardVersionHistoryLogicType'

export interface DashboardVersionHistoryLogicProps {
    dashboardId: number
}

export const dashboardVersionHistoryLogic = kea<dashboardVersionHistoryLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardVersionHistoryLogic', key]),
    props({} as DashboardVersionHistoryLogicProps),
    key((props) => props.dashboardId),
    actions({
        openVersionHistory: true,
        closeVersionHistory: true,
        revertToVersion: (versionId: string) => ({ versionId }),
        revertSucceeded: (versionId: string) => ({ versionId }),
        revertFailed: (error: string) => ({ error }),
    }),
    reducers({
        isOpen: [
            false,
            {
                openVersionHistory: () => true,
                closeVersionHistory: () => false,
            },
        ],
        revertingVersionId: [
            null as string | null,
            {
                revertToVersion: (_, { versionId }) => versionId,
                revertSucceeded: () => null,
                revertFailed: () => null,
                closeVersionHistory: () => null,
            },
        ],
    }),
    loaders(({ props }) => ({
        versions: [
            [] as DashboardVersionListItem[],
            {
                loadVersions: async () => {
                    return await api.dashboards.listVersions(props.dashboardId, { limit: 100 })
                },
            },
        ],
    })),
    listeners(({ actions, props }) => ({
        openVersionHistory: () => {
            actions.loadVersions()
        },
        revertToVersion: async ({ versionId }) => {
            try {
                await api.dashboards.revertToVersion(props.dashboardId, versionId)
                actions.revertSucceeded(versionId)
                // Refresh the version list so the new revert entry appears at the top,
                // and reload the dashboard to reflect the restored values.
                actions.loadVersions()
                dashboardLogic
                    .findMounted({ id: props.dashboardId })
                    ?.actions.loadDashboard({ action: DashboardLoadAction.Update })
                lemonToast.success('Dashboard reverted to selected version')
            } catch (error: any) {
                const message: string = error?.detail || error?.message || 'Could not revert dashboard'
                actions.revertFailed(message)
                lemonToast.error(message)
            }
        },
    })),
])

import { kea } from 'kea'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogicType } from 'types/layout/navigation/navigationLogicType'
import { UserType } from '~/types'

export const navigationLogic = kea<navigationLogicType<UserType>>({
    actions: {
        setMenuCollapsed: (collapsed) => ({ collapsed }),
        collapseMenu: () => {},
        setSystemStatus: (status) => ({ status }),
        setChangelogModalOpen: (isOpen) => ({ isOpen }),
        updateCurrentOrganization: (id) => ({ id }),
        updateCurrentProject: (id, dest) => ({ id, dest }),
        setToolbarModalOpen: (isOpen) => ({ isOpen }),
    },
    reducers: {
        menuCollapsed: [
            typeof window !== 'undefined' && window.innerWidth <= 991,
            {
                setMenuCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
        changelogModalOpen: [
            false,
            {
                setChangelogModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        toolbarModalOpen: [
            false,
            {
                setToolbarModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
    },
    selectors: {
        systemStatus: [
            () => [systemStatusLogic.selectors.systemStatus, systemStatusLogic.selectors.systemStatusLoading],
            (statusMetrics, statusLoading) => {
                if (statusLoading) {
                    return true
                }
                const aliveMetrics = ['redis_alive', 'db_alive']
                let aliveSignals = 0
                for (const metric of statusMetrics) {
                    if (aliveMetrics.includes(metric.key) && metric.value) {
                        aliveSignals = aliveSignals + 1
                    }
                    if (aliveSignals >= aliveMetrics.length) {
                        return true
                    }
                }
                return false
            },
        ],
        updateAvailable: [
            (selectors) => [selectors.latestVersion, selectors.latestVersionLoading, userLogic.selectors.user],
            (latestVersion, latestVersionLoading, user) => {
                // Always latest version in multitenancy
                return !latestVersionLoading && !user?.is_multi_tenancy && latestVersion !== user?.posthog_version
            },
        ],
        currentTeam: [
            () => [userLogic.selectors.user],
            (user) => {
                return user?.team.id
            },
        ],
    },
    loaders: {
        latestVersion: [
            null as string | null,
            {
                loadLatestVersion: async () => {
                    const versions = await api.get('https://update.posthog.com/versions')
                    return versions[0].version
                },
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        collapseMenu: () => {
            if (!values.menuCollapsed && window.innerWidth <= 991) {
                actions.setMenuCollapsed(true)
            }
        },
        updateCurrentOrganization: async ({ id }) => {
            await api.update('api/user', {
                user: { current_organization_id: id },
            })
            location.href = '/'
        },
        updateCurrentProject: async ({ id, dest }) => {
            if (values.currentTeam === id) {
                return
            }
            await api.update('api/user', {
                user: { current_team_id: id },
            })
            location.href = dest
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLatestVersion()
        },
    }),
})

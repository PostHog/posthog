import { kea } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { navigationLogicType } from 'types/layout/navigation/navigationLogicType'

export const navigationLogic = kea<navigationLogicType>({
    actions: {
        setMenuCollapsed: (collapsed) => ({ collapsed }),
        collapseMenu: () => {},
        setSystemStatus: (status) => ({ status }),
    },
    reducers: {
        menuCollapsed: [
            typeof window !== 'undefined' && window.innerWidth <= 991,
            {
                setMenuCollapsed: (_, { collapsed }) => collapsed,
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
                    if (aliveMetrics.indexOf(metric.key) > -1 && metric.value) {
                        aliveSignals = aliveSignals + 1
                    }
                    if (aliveSignals >= aliveMetrics.length) {
                        return true
                    }
                }
                return false
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        collapseMenu: () => {
            if (!values.menuCollapsed && window.innerWidth <= 991) {
                actions.setMenuCollapsed(true)
            }
        },
    }),
    events: () => ({
        afterMount: () => systemStatusLogic.actions.loadSystemStatus(),
    }),
})

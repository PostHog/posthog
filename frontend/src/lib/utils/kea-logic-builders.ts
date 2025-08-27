import { BuiltLogic, afterMount, listeners } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

/**
 * Some kea logics are used heavily across multiple areas so we keep it mounted once loaded with this trick.
 */
export function permanentlyMount(): (logic: BuiltLogic) => void {
    return (logic) => {
        afterMount(() => {
            if (!logic.cache._permanentMount) {
                logic.cache._permanentMount = true
                logic.wrapper.mount()
            }
        })(logic)
    }
}

/**
 * Runs callback after mount and when organization loads, only if organization exists.
 * This abstracts the common pattern of checking for organizationLogic.values.currentOrganization before executing logic.
 */
export function afterMountAndOrganization(
    callback: (props: { actions: any; values: any; props: any }) => void
): (logic: BuiltLogic) => void {
    return (logic) => {
        listeners(() => ({
            [organizationLogic.actionTypes.loadCurrentOrganizationSuccess]: ({ currentOrganization }) => {
                if (currentOrganization) {
                    callback({ actions: logic.actions, values: logic.values, props: logic.props })
                }
            },
        }))(logic)

        afterMount(({ actions, values, props }) => {
            if (organizationLogic.values.currentOrganization) {
                callback({ actions, values, props })
            }
        })(logic)
    }
}
/**
 * Runs callback after mount and when project loads, only if project exists.
 * This mirrors afterMountAndOrganization for project-level data.
 */
export function afterMountAndTeam(
    callback: (props: { actions: any; values: any; props: any }) => void
): (logic: BuiltLogic) => void {
    return (logic) => {
        listeners(() => ({
            [projectLogic.actionTypes.loadCurrentProjectSuccess]: ({ currentProject }) => {
                if (currentProject) {
                    callback({ actions: logic.actions, values: logic.values, props: logic.props })
                }
            },
        }))(logic)

        afterMount(({ actions, values, props }) => {
            if (projectLogic.values.currentProject) {
                callback({ actions, values, props })
            }
        })(logic)
    }
}

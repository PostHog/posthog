import Fuse from 'fuse.js'
import { actions, connect, kea, key, listeners, reducers, selectors, path, props } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { posthog } from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'

import type { sceneDashboardChoiceModalLogicType } from './sceneDashboardChoiceModalLogicType'

export type DashboardCompatibleScenes = Scene.ProjectHomepage | Scene.Person | Scene.Group

export interface SceneDashboardChoiceModalProps {
    scene: DashboardCompatibleScenes
}

export const sceneDashboardChoiceModalLogic = kea<sceneDashboardChoiceModalLogicType>([
    path((key) => ['lib', 'components', 'SceneDashboardChoice', 'sceneDashboardChoiceModalLogic', key || 'unknown']),
    props({} as SceneDashboardChoiceModalProps),
    key((props) => `${props.scene}`),
    connect({
        logic: [eventUsageLogic],
        actions: [teamLogic, ['updateCurrentTeam']],
        values: [teamLogic, ['currentTeam'], dashboardsModel, ['nameSortedDashboards']],
    }),
    actions({
        showSceneDashboardChoiceModal: () => true,
        closeSceneDashboardChoiceModal: () => true,
        setSceneDashboardChoice: (dashboardId: number) => ({ dashboardId }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        searchTerm: [null as string | null, { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        isOpen: [false, { showSceneDashboardChoiceModal: () => true, closeSceneDashboardChoiceModal: () => false }],
    }),
    selectors({
        primaryDashboardId: [(s) => [s.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboards: [
            (s) => [s.searchTerm, s.nameSortedDashboards],
            (searchTerm, dashboards) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                if (!searchTerm) {
                    return dashboards
                }
                return new Fuse(dashboards, {
                    keys: ['key', 'name', 'description', 'tags'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSceneDashboardChoice: async ({ dashboardId }) => {
            actions.updateCurrentTeam({ primary_dashboard: dashboardId })
            // TODO needs to report scene and dashboard
            posthog.capture('primary dashboard changed')
        },
        showSceneDashboardChoiceModal: async () => {
            //TODO needs to report scene
            posthog.capture('primary dashboard modal opened')
        },
    })),
])

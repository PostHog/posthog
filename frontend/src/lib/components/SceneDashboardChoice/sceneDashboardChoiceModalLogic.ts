import Fuse from 'fuse.js'
import { actions, connect, kea, key, listeners, reducers, selectors, path, props } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { posthog } from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'

import type { sceneDashboardChoiceModalLogicType } from './sceneDashboardChoiceModalLogicType'
import { userLogic } from 'scenes/userLogic'

export type DashboardCompatibleScenes = Scene.ProjectHomepage | Scene.Person | Scene.Group

export interface SceneDashboardChoiceModalProps {
    scene: DashboardCompatibleScenes
}

export const sceneDescription: Record<DashboardCompatibleScenes, string> = {
    [Scene.Person]: 'persons',
    [Scene.Group]: 'groups',
    [Scene.ProjectHomepage]: 'this project',
}

export const sceneDashboardChoiceModalLogic = kea<sceneDashboardChoiceModalLogicType>([
    path((key) => ['lib', 'components', 'SceneDashboardChoice', 'sceneDashboardChoiceModalLogic', key || 'unknown']),
    props({} as SceneDashboardChoiceModalProps),
    key((props) => `${props.scene}`),
    connect({
        logic: [eventUsageLogic],
        actions: [teamLogic, ['updateCurrentTeam'], userLogic, ['setUserSceneDashboardChoice']],
        values: [teamLogic, ['currentTeam'], userLogic, ['user'], dashboardsModel, ['nameSortedDashboards']],
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
    selectors(({ props }) => ({
        currentDashboardId: [
            (s) => [s.currentTeam, s.user],
            (currentTeam, user) => {
                let currentDashboard = user?.scene_dashboard_choices?.find(
                    (choice) => choice.scene === props.scene
                )?.dashboard

                if (!currentDashboard && props.scene === Scene.ProjectHomepage) {
                    currentDashboard = currentTeam?.primary_dashboard
                }

                return (typeof currentDashboard === 'number' ? currentDashboard : currentDashboard?.id) ?? null
            },
        ],
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
    })),
    listeners(({ actions, props }) => ({
        setSceneDashboardChoice: async ({ dashboardId }) => {
            // TODO needs to report scene and dashboard
            if (props.scene === Scene.ProjectHomepage) {
                // TODO be able to save individual or team level home dashboard
                actions.updateCurrentTeam({ primary_dashboard: dashboardId })
                posthog.capture('primary dashboard changed')
            } else {
                actions.setUserSceneDashboardChoice(props.scene, dashboardId)
                posthog.capture('scene dashboard choice set', { scene: props.scene, dashboardId: dashboardId })
            }
        },
        showSceneDashboardChoiceModal: async () => {
            if (props.scene === Scene.ProjectHomepage) {
                posthog.capture('primary dashboard modal opened')
            } else {
                posthog.capture('scene dashboard choice modal opened', { scene: props.scene })
            }
        },
    })),
])

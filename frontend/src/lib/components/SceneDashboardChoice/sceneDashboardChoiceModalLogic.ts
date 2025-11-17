import Fuse from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import type { sceneDashboardChoiceModalLogicType } from './sceneDashboardChoiceModalLogicType'

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
    connect(() => ({
        logic: [eventUsageLogic],
        actions: [teamLogic, ['updateCurrentTeam'], userLogic, ['setUserScenePersonalisation']],
        values: [teamLogic, ['currentTeam'], userLogic, ['user'], dashboardsModel, ['nameSortedDashboards']],
    })),
    actions({
        showSceneDashboardChoiceModal: () => true,
        closeSceneDashboardChoiceModal: () => true,
        setSceneDashboardChoice: (dashboardId: number | null) => ({ dashboardId }),
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
                let currentDashboard: number | DashboardBasicType | null =
                    user?.scene_personalisation?.find((choice) => choice.scene === props.scene)?.dashboard ?? null

                if (!currentDashboard && props.scene === Scene.ProjectHomepage) {
                    currentDashboard = currentTeam?.primary_dashboard ?? null
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
                actions.updateCurrentTeam({ primary_dashboard: dashboardId ?? null })
                posthog.capture('primary dashboard changed')
            } else {
                actions.setUserScenePersonalisation(props.scene, dashboardId ?? 0)
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

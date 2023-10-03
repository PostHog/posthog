import {
    IconApps,
    IconBarChart,
    IconCohort,
    IconComment,
    IconCottage,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconLive,
    IconPerson,
    IconRecording,
    IconTools,
    IconUnverifiedEvent,
} from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { NavbarItem } from './types'
import { dashboardsSidebarLogic } from './sidebars/dashboards'
import { featureFlagsSidebarLogic } from './sidebars/featureFlags'
import { cohortsSidebarLogic } from './sidebars/cohorts'
import { personsAndGroupsSidebarLogic } from './sidebars/personsAndGroups'
import { insightsSidebarLogic } from './sidebars/insights'
import { dataManagementSidebarLogic } from './sidebars/dataManagement'
import { annotationsSidebarLogic } from './sidebars/annotations'
import { experimentsSidebarLogic } from './sidebars/experiments'
import { toolbarSidebarLogic } from './sidebars/toolbar'

/** A list of navbar sections with items. */
export const NAVBAR_ITEMS: NavbarItem[][] = [
    [
        {
            identifier: Scene.ProjectHomepage,
            label: 'Project homepage',
            icon: <IconCottage />,
            to: urls.projectHomepage(),
        },
        {
            identifier: Scene.Dashboards,
            label: 'Dashboards',
            icon: <IconGauge />,
            logic: dashboardsSidebarLogic,
        },
        {
            identifier: Scene.DataManagement,
            label: 'Data management',
            icon: <IconUnverifiedEvent />,
            logic: dataManagementSidebarLogic,
        },
        {
            identifier: Scene.Persons,
            label: 'Persons and groups',
            icon: <IconPerson />,
            logic: personsAndGroupsSidebarLogic,
        },
        {
            identifier: Scene.Cohorts,
            label: 'Cohorts',
            icon: <IconCohort />,
            logic: cohortsSidebarLogic,
        },
        {
            identifier: Scene.Annotations,
            label: 'Annotations',
            icon: <IconComment />,
            logic: annotationsSidebarLogic,
        },
    ],
    [
        {
            identifier: Scene.Events,
            label: 'Events',
            icon: <IconLive />,
        },
        {
            identifier: Scene.SavedInsights,
            label: 'Product Analytics',
            icon: <IconBarChart />,
            logic: insightsSidebarLogic,
        },
        {
            identifier: Scene.Replay,
            label: 'Session Replay',
            icon: <IconRecording />,
        },
        {
            identifier: Scene.FeatureFlags,
            label: 'Feature Flags',
            icon: <IconFlag />,
            logic: featureFlagsSidebarLogic,
        },
        {
            identifier: Scene.Experiments,
            label: 'A/B Testing',
            icon: <IconExperiment />,
            logic: experimentsSidebarLogic,
        },
        {
            identifier: Scene.ToolbarLaunch,
            label: 'Toolbar',
            icon: <IconTools />,
            logic: toolbarSidebarLogic,
        },
    ],
    [
        {
            identifier: Scene.Apps,
            label: 'Apps',
            icon: <IconApps />,
        },
    ],
]

export const NAVBAR_ITEM_ID_TO_ITEM: Record<string, NavbarItem> = Object.fromEntries(
    NAVBAR_ITEMS.flat().map((item) => [item.identifier, item])
)

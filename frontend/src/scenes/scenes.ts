import { Params, Scene, SceneConfig, LoadedScene } from 'scenes/sceneTypes'
import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'

export const emptySceneParams = { params: {}, searchParams: {}, hashParams: {} }

export const preloadedScenes: Record<string, LoadedScene> = {
    [Scene.Error404]: {
        name: Scene.Error404,
        component: Error404Component,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorNetwork]: {
        name: Scene.ErrorNetwork,
        component: ErrorNetworkComponent,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorProjectUnavailable]: {
        name: Scene.ErrorProjectUnavailable,
        component: ErrorProjectUnavailableComponent,
        sceneParams: emptySceneParams,
    },
}

export const sceneConfigurations: Partial<Record<Scene, SceneConfig>> = {
    // Project-based routes
    [Scene.Dashboards]: {
        projectBased: true,
        name: 'Dashboards',
    },
    [Scene.Dashboard]: {
        projectBased: true,
    },
    [Scene.Insight]: {
        projectBased: true,
        name: 'Insights',
    },
    [Scene.Cohorts]: {
        projectBased: true,
        name: 'Cohorts',
    },
    [Scene.Cohort]: {
        projectBased: true,
        name: 'Cohort',
    },
    [Scene.Events]: {
        projectBased: true,
        name: 'Live Events',
    },
    [Scene.DataManagement]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.Actions]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.EventDefinitions]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.EventDefinition]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.EventPropertyDefinitions]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.EventPropertyDefinition]: {
        projectBased: true,
        name: 'Data Management',
    },
    [Scene.WebPerformance]: {
        projectBased: true,
        name: 'Web Performance',
    },
    [Scene.SessionRecordings]: {
        projectBased: true,
        name: 'Recordings',
    },
    [Scene.Person]: {
        projectBased: true,
        name: 'Person',
    },
    [Scene.Persons]: {
        projectBased: true,
        name: 'Persons & Groups',
    },
    [Scene.Action]: {
        projectBased: true,
        name: 'Action',
    },
    [Scene.Groups]: {
        projectBased: true,
        name: 'Persons & Groups',
    },
    [Scene.Group]: {
        projectBased: true,
        name: 'Persons & Groups',
    },
    [Scene.Experiments]: {
        projectBased: true,
        name: 'Experiments',
    },
    [Scene.Experiment]: {
        projectBased: true,
        name: 'Experiment',
    },
    [Scene.FeatureFlags]: {
        projectBased: true,
        name: 'Feature Flags',
    },
    [Scene.FeatureFlag]: {
        projectBased: true,
    },
    [Scene.Annotations]: {
        projectBased: true,
        name: 'Annotations',
    },
    [Scene.Plugins]: {
        projectBased: true,
        name: 'Apps',
    },
    [Scene.FrontendAppScene]: {
        projectBased: true,
        name: 'App',
    },
    [Scene.SavedInsights]: {
        projectBased: true,
        name: 'Insights',
    },
    [Scene.ProjectHomepage]: {
        projectBased: true,
        name: 'Homepage',
    },
    [Scene.ProjectSettings]: {
        projectBased: true,
        hideDemoWarnings: true,
        name: 'Project settings',
    },
    [Scene.IntegrationsRedirect]: {
        name: 'Integrations Redirect',
    },
    [Scene.Ingestion]: {
        projectBased: true,
        plain: true,
    },
    [Scene.ToolbarLaunch]: {
        projectBased: true,
        name: 'Toolbar',
    },
    // Organization-based routes
    [Scene.OrganizationCreateFirst]: {
        name: 'Organization creation',
    },
    [Scene.OrganizationCreationConfirm]: {
        name: 'Confirm organization creation',
        onlyUnauthenticated: true,
    },
    [Scene.OrganizationSettings]: {
        organizationBased: true,
    },
    [Scene.ProjectCreateFirst]: {
        name: 'Project creation',
        organizationBased: true,
    },
    // Onboarding/setup routes
    [Scene.Login]: {
        onlyUnauthenticated: true,
    },
    [Scene.Signup]: {
        onlyUnauthenticated: true,
    },
    [Scene.PreflightCheck]: {
        onlyUnauthenticated: true,
    },
    [Scene.PasswordReset]: {
        allowUnauthenticated: true,
    },
    [Scene.PasswordResetComplete]: {
        allowUnauthenticated: true,
    },
    [Scene.InviteSignup]: {
        allowUnauthenticated: true,
        plain: true,
    },
    // Instance management routes
    [Scene.SystemStatus]: {
        instanceLevel: true,
        name: 'Instance status & settings',
    },
    [Scene.Licenses]: {
        instanceLevel: true,
    },
    [Scene.AsyncMigrations]: {
        instanceLevel: true,
    },
    [Scene.DeadLetterQueue]: {
        instanceLevel: true,
    },
    // Personal routes
    [Scene.MySettings]: {
        personal: true,
    },
    // Cloud-only routes
    [Scene.Billing]: {
        hideDemoWarnings: true,
        organizationBased: true,
    },
    [Scene.BillingSubscribed]: {
        plain: true,
        allowUnauthenticated: true,
    },
    [Scene.Unsubscribe]: {
        allowUnauthenticated: true,
    },
}

export const redirects: Record<string, string | ((params: Params) => string)> = {
    '/': urls.projectHomepage(),
    '/saved_insights': urls.savedInsights(),
    '/dashboards': urls.dashboards(),
    '/plugins': urls.projectApps(),
    '/project/plugins': urls.projectApps(),
    '/actions': urls.actions(), // TODO: change to urls.eventDefinitions() when "simplify-actions" FF is released
    '/organization/members': urls.organizationSettings(),
    '/i/:shortId': ({ shortId }) => urls.insightView(shortId),
    '/action/:id': ({ id }) => urls.action(id),
    '/action': urls.createAction(),
    '/events/actions': urls.actions(), // TODO: change to urls.eventDefinitions() when "simplify-actions" FF is released
    '/events/stats': urls.eventDefinitions(),
    '/events/stats/:id': ({ id }) => urls.eventDefinition(id),
    '/events/properties': urls.eventPropertyDefinitions(),
    '/events/properties/:id': ({ id }) => urls.eventPropertyDefinition(id),
}

export const routes: Record<string, Scene> = {
    [urls.dashboards()]: Scene.Dashboards,
    [urls.dashboard(':id')]: Scene.Dashboard,
    [urls.dashboardSubcriptions(':id')]: Scene.Dashboard,
    [urls.dashboardSubcription(':id', ':subscriptionId')]: Scene.Dashboard,
    [urls.createAction()]: Scene.Action,
    [urls.action(':id')]: Scene.Action,
    [urls.insightNew()]: Scene.Insight,
    [urls.insightEdit(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightView(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcriptions(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcription(':shortId' as InsightShortId, ':subscriptionId')]: Scene.Insight,
    [urls.insightEmbed(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.savedInsights()]: Scene.SavedInsights,
    [urls.actions()]: Scene.Actions, // TODO: remove when "simplify-actions" FF is released
    [urls.eventDefinitions()]: Scene.EventDefinitions,
    [urls.eventDefinition(':id')]: Scene.EventDefinition,
    [urls.eventPropertyDefinitions()]: Scene.EventPropertyDefinitions,
    [urls.eventPropertyDefinition(':id')]: Scene.EventPropertyDefinition,
    [urls.events()]: Scene.Events,
    [urls.webPerformance()]: Scene.WebPerformance,
    [urls.webPerformance() + '/*']: Scene.WebPerformance,
    [urls.sessionRecordings()]: Scene.SessionRecordings,
    [urls.person('*', false)]: Scene.Person,
    [urls.persons()]: Scene.Persons,
    [urls.groups(':groupTypeIndex')]: Scene.Groups,
    [urls.group(':groupTypeIndex', ':groupKey', false)]: Scene.Group,
    [urls.cohort(':id')]: Scene.Cohort,
    [urls.cohorts()]: Scene.Cohorts,
    [urls.experiments()]: Scene.Experiments,
    [urls.experiment(':id')]: Scene.Experiment,
    [urls.featureFlags()]: Scene.FeatureFlags,
    [urls.featureFlag(':id')]: Scene.FeatureFlag,
    [urls.annotations()]: Scene.Annotations,
    [urls.projectHomepage()]: Scene.ProjectHomepage,
    [urls.projectSettings()]: Scene.ProjectSettings,
    [urls.projectApps()]: Scene.Plugins,
    [urls.frontendApp(':id')]: Scene.FrontendAppScene,
    [urls.projectCreateFirst()]: Scene.ProjectCreateFirst,
    [urls.organizationSettings()]: Scene.OrganizationSettings,
    [urls.organizationBilling()]: Scene.Billing,
    [urls.billingSubscribed()]: Scene.BillingSubscribed,
    [urls.organizationCreateFirst()]: Scene.OrganizationCreateFirst,
    [urls.organizationCreationConfirm()]: Scene.OrganizationCreationConfirm,
    [urls.instanceLicenses()]: Scene.Licenses,
    [urls.instanceStatus()]: Scene.SystemStatus,
    [urls.instanceSettings()]: Scene.SystemStatus,
    [urls.instanceStaffUsers()]: Scene.SystemStatus,
    [urls.instanceKafkaInspector()]: Scene.SystemStatus,
    [urls.instanceMetrics()]: Scene.SystemStatus,
    [urls.asyncMigrations()]: Scene.AsyncMigrations,
    [urls.deadLetterQueue()]: Scene.DeadLetterQueue,
    [urls.mySettings()]: Scene.MySettings,
    [urls.toolbarLaunch()]: Scene.ToolbarLaunch,
    // Onboarding / setup routes
    [urls.login()]: Scene.Login,
    [urls.preflight()]: Scene.PreflightCheck,
    [urls.signup()]: Scene.Signup,
    [urls.inviteSignup(':id')]: Scene.InviteSignup,
    [urls.passwordReset()]: Scene.PasswordReset,
    [urls.passwordResetComplete(':uuid', ':token')]: Scene.PasswordResetComplete,
    [urls.ingestion()]: Scene.Ingestion,
    [urls.ingestion() + '/*']: Scene.Ingestion,
    [urls.unsubscribe()]: Scene.Unsubscribe,
    [urls.integrationsRedirect(':kind')]: Scene.IntegrationsRedirect,
}

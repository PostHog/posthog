import { combineUrl } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getDefaultEventsSceneQuery } from 'scenes/events/defaults'
import { LoadedScene, Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { EventsQuery } from '~/queries/schema'
import { ActivityScope, InsightShortId, PropertyFilterType, ReplayTabs } from '~/types'

export const emptySceneParams = { params: {}, searchParams: {}, hashParams: {} }

export const preloadedScenes: Record<string, LoadedScene> = {
    [Scene.Error404]: {
        id: Scene.Error404,
        component: Error404Component,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorNetwork]: {
        id: Scene.ErrorNetwork,
        component: ErrorNetworkComponent,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorProjectUnavailable]: {
        id: Scene.ErrorProjectUnavailable,
        component: ErrorProjectUnavailableComponent,
        sceneParams: emptySceneParams,
    },
}

export const sceneConfigurations: Record<Scene, SceneConfig> = {
    [Scene.Error404]: {
        name: 'Not found',
        projectBased: true,
    },
    [Scene.ErrorNetwork]: {
        name: 'Network error',
    },
    [Scene.ErrorProjectUnavailable]: {
        name: 'Project unavailable',
    },
    // Project-based routes
    [Scene.Dashboards]: {
        projectBased: true,
        name: 'Dashboards',
        activityScope: ActivityScope.DASHBOARD,
    },
    [Scene.Dashboard]: {
        projectBased: true,
        activityScope: ActivityScope.DASHBOARD,
        defaultDocsPath: '/docs/product-analytics/dashboards',
    },
    [Scene.Insight]: {
        projectBased: true,
        name: 'Insights',
        activityScope: ActivityScope.INSIGHT,
        defaultDocsPath: '/docs/product-analytics/insights',
    },
    [Scene.WebAnalytics]: {
        projectBased: true,
        name: 'Web analytics',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics',
    },
    [Scene.Cohort]: {
        projectBased: true,
        name: 'Cohort',
        defaultDocsPath: '/docs/data/cohorts',
    },
    [Scene.Events]: {
        projectBased: true,
        name: 'Activity',
        defaultDocsPath: '/docs/data/events',
    },
    [Scene.BatchExports]: {
        projectBased: true,
        name: 'Batch exports',
        defaultDocsPath: '/docs/cdp/batch-exports',
    },
    [Scene.BatchExportEdit]: {
        projectBased: true,
        name: 'Edit batch export',
        defaultDocsPath: '/docs/cdp/batch-exports',
    },
    [Scene.BatchExport]: {
        projectBased: true,
        name: 'Batch export',
        defaultDocsPath: '/docs/cdp/batch-exports',
    },
    [Scene.DataManagement]: {
        projectBased: true,
        name: 'Data management',
        activityScope: ActivityScope.DATA_MANAGEMENT,
        defaultDocsPath: '/docs/data',
    },
    [Scene.EventDefinition]: {
        projectBased: true,
        name: 'Data management',
        activityScope: ActivityScope.EVENT_DEFINITION,
        defaultDocsPath: '/docs/data/events',
    },
    [Scene.PropertyDefinition]: {
        projectBased: true,
        name: 'Data management',
        activityScope: ActivityScope.PROPERTY_DEFINITION,
    },
    [Scene.Replay]: {
        projectBased: true,
        name: 'Session replay',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.ReplaySingle]: {
        projectBased: true,
        name: 'Replay recording',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.ReplayPlaylist]: {
        projectBased: true,
        name: 'Replay playlist',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.Person]: {
        projectBased: true,
        name: 'Person',
        activityScope: ActivityScope.PERSON,
        defaultDocsPath: '/docs/data/persons',
    },
    [Scene.PersonsManagement]: {
        projectBased: true,
        name: 'People & groups',
        activityScope: ActivityScope.PERSON,
        defaultDocsPath: '/docs/data/persons',
    },
    [Scene.Action]: {
        projectBased: true,
        name: 'Action',
        defaultDocsPath: '/docs/data/actions',
    },
    [Scene.Group]: {
        projectBased: true,
        name: 'People & groups',
        defaultDocsPath: '/docs/product-analytics/group-analytics',
    },
    [Scene.Pipeline]: {
        projectBased: true,
        name: 'Pipeline',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.PipelineNode]: {
        projectBased: true,
        name: 'Pipeline step',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.Experiments]: {
        projectBased: true,
        name: 'A/B testing',
        defaultDocsPath: '/docs/experiments',
        activityScope: ActivityScope.EXPERIMENT,
    },
    [Scene.Experiment]: {
        projectBased: true,
        name: 'Experiment',
        defaultDocsPath: '/docs/experiments/creating-an-experiment',
        activityScope: ActivityScope.EXPERIMENT,
    },
    [Scene.FeatureFlags]: {
        projectBased: true,
        name: 'Feature flags',
        defaultDocsPath: '/docs/feature-flags',
        activityScope: ActivityScope.FEATURE_FLAG,
    },
    [Scene.FeatureFlag]: {
        projectBased: true,
        activityScope: ActivityScope.FEATURE_FLAG,
        defaultDocsPath: '/docs/feature-flags/creating-feature-flags',
    },
    [Scene.Surveys]: {
        projectBased: true,
        name: 'Surveys',
        defaultDocsPath: '/docs/surveys',
        activityScope: ActivityScope.SURVEY,
    },
    [Scene.Survey]: {
        projectBased: true,
        name: 'Survey',
        defaultDocsPath: '/docs/surveys',
        activityScope: ActivityScope.SURVEY,
    },
    [Scene.SurveyTemplates]: {
        projectBased: true,
        name: 'New survey',
        defaultDocsPath: '/docs/surveys/creating-surveys',
    },
    [Scene.DataWarehouse]: {
        projectBased: true,
        name: 'Data warehouse',
        defaultDocsPath: '/docs/data-warehouse',
    },
    [Scene.DataWarehouseExternal]: {
        projectBased: true,
        name: 'Data warehouse',
        defaultDocsPath: '/docs/data-warehouse/setup',
    },
    [Scene.DataWarehouseSettings]: {
        projectBased: true,
        name: 'Data warehouse settings',
        defaultDocsPath: '/docs/data-warehouse',
    },
    [Scene.DataWarehouseRedirect]: {
        name: 'Data warehouse redirect',
    },
    [Scene.DataWarehouseTable]: {
        projectBased: true,
        name: 'Data warehouse table',
        defaultDocsPath: '/docs/data-warehouse',
    },
    [Scene.EarlyAccessFeatures]: {
        projectBased: true,
        defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
        activityScope: ActivityScope.EARLY_ACCESS_FEATURE,
    },
    [Scene.EarlyAccessFeature]: {
        projectBased: true,
        defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
        activityScope: ActivityScope.EARLY_ACCESS_FEATURE,
    },
    [Scene.Apps]: {
        projectBased: true,
        name: 'Apps',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.FrontendAppScene]: {
        projectBased: true,
        name: 'App',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.AppMetrics]: {
        projectBased: true,
        name: 'Apps',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.SavedInsights]: {
        projectBased: true,
        name: 'Product analytics',
        activityScope: ActivityScope.INSIGHT,
        defaultDocsPath: '/docs/product-analytics',
    },
    [Scene.ProjectHomepage]: {
        projectBased: true,
        name: 'Homepage',
    },
    [Scene.IntegrationsRedirect]: {
        name: 'Integrations redirect',
    },
    [Scene.Products]: {
        projectBased: true,
        hideProjectNotice: true,
    },
    [Scene.Onboarding]: {
        projectBased: true,
        hideProjectNotice: true,
    },
    [Scene.OnboardingProductIntroduction]: {
        projectBased: true,
        name: 'Product introduction',
        hideProjectNotice: true,
    },
    [Scene.ToolbarLaunch]: {
        projectBased: true,
        name: 'Launch toolbar',
        defaultDocsPath: '/docs/toolbar',
    },
    [Scene.Site]: {
        projectBased: true,
        hideProjectNotice: true,
        layout: 'app-raw',
    },
    // Organization-based routes
    [Scene.OrganizationCreateFirst]: {
        name: 'Organization creation',
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    [Scene.OrganizationCreationConfirm]: {
        name: 'Confirm organization creation',
        onlyUnauthenticated: true,
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    [Scene.ProjectCreateFirst]: {
        name: 'Project creation',
        organizationBased: true,
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    // Onboarding/setup routes
    [Scene.Login]: {
        onlyUnauthenticated: true,
    },
    [Scene.Login2FA]: {
        onlyUnauthenticated: true,
    },
    [Scene.Signup]: {
        onlyUnauthenticated: true,
    },
    [Scene.PreflightCheck]: {
        onlyUnauthenticated: true,
    },
    [Scene.PasswordReset]: {
        onlyUnauthenticated: true,
    },
    [Scene.PasswordResetComplete]: {
        onlyUnauthenticated: true,
    },
    [Scene.InviteSignup]: {
        allowUnauthenticated: true,
        layout: 'plain',
    },
    // Instance management routes
    [Scene.SystemStatus]: {
        instanceLevel: true,
        name: 'Instance panel',
    },
    [Scene.AsyncMigrations]: {
        instanceLevel: true,
    },
    [Scene.DeadLetterQueue]: {
        instanceLevel: true,
    },
    // Cloud-only routes
    [Scene.Billing]: {
        hideProjectNotice: true,
        organizationBased: true,
        defaultDocsPath: '/pricing',
    },
    [Scene.Unsubscribe]: {
        allowUnauthenticated: true,
        layout: 'app-raw',
    },
    [Scene.DebugQuery]: {
        projectBased: true,
    },
    [Scene.VerifyEmail]: {
        allowUnauthenticated: true,
        layout: 'plain',
    },
    [Scene.Notebook]: {
        projectBased: true,
        hideProjectNotice: true, // Currently doesn't render well...
        name: 'Notebook',
        layout: 'app-raw',
        activityScope: ActivityScope.NOTEBOOK,
        defaultDocsPath: '/blog/introducing-notebooks',
    },
    [Scene.Notebooks]: {
        projectBased: true,
        name: 'Notebooks',
        activityScope: ActivityScope.NOTEBOOK,
        defaultDocsPath: '/blog/introducing-notebooks',
    },
    [Scene.Canvas]: {
        projectBased: true,
        name: 'Canvas',
        layout: 'app-raw',
        defaultDocsPath: '/blog/introducing-notebooks',
    },
    [Scene.Settings]: {
        projectBased: true,
        name: 'Settings',
    },
    [Scene.MoveToPostHogCloud]: {
        name: 'Move to PostHog Cloud',
        hideProjectNotice: true,
    },
}

const preserveParams = (url: string) => (_params: Params, searchParams: Params, hashParams: Params) => {
    const combined = combineUrl(url, searchParams, hashParams)
    return combined.url
}

// NOTE: These redirects will fully replace the URL. If you want to keep support for query and hash params then you should use the above `preserveParams` function.
export const redirects: Record<
    string,
    string | ((params: Params, searchParams: Params, hashParams: Params) => string)
> = {
    '/home': urls.projectHomepage(),
    '/saved_insights': urls.savedInsights(),
    '/dashboards': urls.dashboards(),
    '/plugins': urls.projectApps(),
    '/project/plugins': urls.projectApps(),
    '/actions': urls.actions(),
    '/organization/members': urls.settings('organization'),
    '/i/:shortId': ({ shortId }) => urls.insightView(shortId),
    '/action/:id': ({ id }) => urls.action(id),
    '/action': urls.createAction(),
    '/events/actions': urls.actions(),
    '/events/stats': urls.eventDefinitions(),
    '/events/stats/:id': ({ id }) => urls.eventDefinition(id),
    '/events/:id/*': ({ id, _ }) => {
        const query = getDefaultEventsSceneQuery([
            {
                type: PropertyFilterType.HogQL,
                key: `uuid = '${id.replaceAll(/[^a-f0-9-]/g, '')}'`,
                value: null,
            },
        ])
        try {
            const timestamp = decodeURIComponent(_)
            const after = dayjs(timestamp).subtract(1, 'second').startOf('second').toISOString()
            const before = dayjs(timestamp).add(1, 'second').startOf('second').toISOString()
            Object.assign(query.source as EventsQuery, { before, after })
        } catch (e) {
            lemonToast.error('Invalid event timestamp')
        }
        return combineUrl(urls.events(), {}, { q: query }).url
    },
    '/events/properties': urls.propertyDefinitions(),
    '/events/properties/:id': ({ id }) => urls.propertyDefinition(id),
    '/annotations': () => urls.annotations(),
    '/annotations/:id': ({ id }) => urls.annotation(id),
    '/recordings/:id': ({ id }) => urls.replaySingle(id),
    '/recordings/playlists/:id': ({ id }) => urls.replayPlaylist(id),
    '/recordings': (_params, _searchParams, hashParams) => {
        if (hashParams.sessionRecordingId) {
            // Previous URLs for an individual recording were like: /recordings/#sessionRecordingId=foobar
            return urls.replaySingle(hashParams.sessionRecordingId)
        }
        return urls.replay()
    },
    '/replay': urls.replay(),
    '/exports': urls.batchExports(),
    '/settings': urls.settings(),
    '/project/settings': urls.settings('project'),
    '/organization/settings': urls.settings('organization'),
    '/me/settings': urls.settings('user'),
    '/pipeline': urls.pipeline(),
    '/project/apps': preserveParams(urls.projectApps()),
    '/project/apps/:id': ({ id }) => urls.projectApp(id),
    '/instance': urls.instanceStatus(),
}

export const routes: Record<string, Scene> = {
    [urls.dashboards()]: Scene.Dashboards,
    [urls.dashboard(':id')]: Scene.Dashboard,
    [urls.dashboardTextTile(':id', ':textTileId')]: Scene.Dashboard,
    [urls.dashboardSharing(':id')]: Scene.Dashboard,
    [urls.dashboardSubcriptions(':id')]: Scene.Dashboard,
    [urls.dashboardSubcription(':id', ':subscriptionId')]: Scene.Dashboard,
    [urls.createAction()]: Scene.Action,
    [urls.copyAction(null)]: Scene.Action,
    [urls.action(':id')]: Scene.Action,
    [urls.ingestionWarnings()]: Scene.DataManagement,
    [urls.insightNew()]: Scene.Insight,
    [urls.insightEdit(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightView(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcriptions(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcription(':shortId' as InsightShortId, ':subscriptionId')]: Scene.Insight,
    [urls.insightSharing(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.savedInsights()]: Scene.SavedInsights,
    [urls.webAnalytics()]: Scene.WebAnalytics,
    [urls.actions()]: Scene.DataManagement,
    [urls.eventDefinitions()]: Scene.DataManagement,
    [urls.eventDefinition(':id')]: Scene.EventDefinition,
    [urls.batchExports()]: Scene.BatchExports,
    [urls.batchExportNew()]: Scene.BatchExportEdit,
    [urls.batchExport(':id')]: Scene.BatchExport,
    [urls.batchExportEdit(':id')]: Scene.BatchExportEdit,
    [urls.propertyDefinitions()]: Scene.DataManagement,
    [urls.propertyDefinition(':id')]: Scene.PropertyDefinition,
    [urls.dataManagementHistory()]: Scene.DataManagement,
    [urls.database()]: Scene.DataManagement,
    [urls.events()]: Scene.Events,
    [urls.replay()]: Scene.Replay,
    // One entry for every available tab
    ...Object.values(ReplayTabs).reduce((acc, tab) => {
        acc[urls.replay(tab)] = Scene.Replay
        return acc
    }, {} as Record<string, Scene>),
    [urls.replaySingle(':id')]: Scene.ReplaySingle,
    [urls.replayPlaylist(':id')]: Scene.ReplayPlaylist,
    [urls.personByDistinctId('*', false)]: Scene.Person,
    [urls.personByUUID('*', false)]: Scene.Person,
    [urls.persons()]: Scene.PersonsManagement,
    [urls.pipeline(':tab')]: Scene.Pipeline,
    [urls.pipelineNode(':stage', ':id', ':nodeTab')]: Scene.PipelineNode,
    [urls.groups(':groupTypeIndex')]: Scene.PersonsManagement,
    [urls.group(':groupTypeIndex', ':groupKey', false)]: Scene.Group,
    [urls.group(':groupTypeIndex', ':groupKey', false, ':groupTab')]: Scene.Group,
    [urls.cohort(':id')]: Scene.Cohort,
    [urls.cohorts()]: Scene.PersonsManagement,
    [urls.experiments()]: Scene.Experiments,
    [urls.experiment(':id')]: Scene.Experiment,
    [urls.earlyAccessFeatures()]: Scene.EarlyAccessFeatures,
    [urls.earlyAccessFeature(':id')]: Scene.EarlyAccessFeature,
    [urls.surveys()]: Scene.Surveys,
    [urls.survey(':id')]: Scene.Survey,
    [urls.surveyTemplates()]: Scene.SurveyTemplates,
    [urls.dataWarehouse()]: Scene.DataWarehouse,
    [urls.dataWarehouseTable()]: Scene.DataWarehouseTable,
    [urls.dataWarehouseSettings()]: Scene.DataWarehouseSettings,
    [urls.dataWarehouseRedirect(':kind')]: Scene.DataWarehouseRedirect,
    [urls.featureFlags()]: Scene.FeatureFlags,
    [urls.featureFlag(':id')]: Scene.FeatureFlag,
    [urls.annotations()]: Scene.DataManagement,
    [urls.annotation(':id')]: Scene.DataManagement,
    [urls.projectHomepage()]: Scene.ProjectHomepage,
    [urls.projectApps()]: Scene.Apps,
    [urls.projectApp(':id')]: Scene.Apps,
    [urls.projectAppLogs(':id')]: Scene.Apps,
    [urls.projectAppSource(':id')]: Scene.Apps,
    [urls.frontendApp(':id')]: Scene.FrontendAppScene,
    [urls.appMetrics(':pluginConfigId')]: Scene.AppMetrics,
    [urls.appHistoricalExports(':pluginConfigId')]: Scene.AppMetrics,
    [urls.appHistory(':pluginConfigId')]: Scene.AppMetrics,
    [urls.appLogs(':pluginConfigId')]: Scene.AppMetrics,
    [urls.projectCreateFirst()]: Scene.ProjectCreateFirst,
    [urls.organizationBilling()]: Scene.Billing,
    [urls.organizationCreateFirst()]: Scene.OrganizationCreateFirst,
    [urls.organizationCreationConfirm()]: Scene.OrganizationCreationConfirm,
    [urls.instanceStatus()]: Scene.SystemStatus,
    [urls.instanceSettings()]: Scene.SystemStatus,
    [urls.instanceStaffUsers()]: Scene.SystemStatus,
    [urls.instanceKafkaInspector()]: Scene.SystemStatus,
    [urls.instanceMetrics()]: Scene.SystemStatus,
    [urls.asyncMigrations()]: Scene.AsyncMigrations,
    [urls.asyncMigrationsFuture()]: Scene.AsyncMigrations,
    [urls.asyncMigrationsSettings()]: Scene.AsyncMigrations,
    [urls.deadLetterQueue()]: Scene.DeadLetterQueue,
    [urls.toolbarLaunch()]: Scene.ToolbarLaunch,
    [urls.site(':url')]: Scene.Site,
    // Onboarding / setup routes
    [urls.login()]: Scene.Login,
    [urls.login2FA()]: Scene.Login2FA,
    [urls.preflight()]: Scene.PreflightCheck,
    [urls.signup()]: Scene.Signup,
    [urls.inviteSignup(':id')]: Scene.InviteSignup,
    [urls.passwordReset()]: Scene.PasswordReset,
    [urls.passwordResetComplete(':uuid', ':token')]: Scene.PasswordResetComplete,
    [urls.products()]: Scene.Products,
    [urls.onboarding(':productKey')]: Scene.Onboarding,
    [urls.onboardingProductIntroduction(':productKey')]: Scene.OnboardingProductIntroduction,
    [urls.verifyEmail()]: Scene.VerifyEmail,
    [urls.verifyEmail(':uuid')]: Scene.VerifyEmail,
    [urls.verifyEmail(':uuid', ':token')]: Scene.VerifyEmail,
    [urls.unsubscribe()]: Scene.Unsubscribe,
    [urls.integrationsRedirect(':kind')]: Scene.IntegrationsRedirect,
    [urls.debugQuery()]: Scene.DebugQuery,
    [urls.notebook(':shortId')]: Scene.Notebook,
    [urls.notebooks()]: Scene.Notebooks,
    [urls.canvas()]: Scene.Canvas,
    [urls.settings(':section' as any)]: Scene.Settings,
    [urls.moveToPostHogCloud()]: Scene.MoveToPostHogCloud,
}

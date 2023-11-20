import { LoadedScene, Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { urls } from 'scenes/urls'
import { InsightShortId, PipelineAppTabs, PipelineTabs, PropertyFilterType, ReplayTabs } from '~/types'
import { combineUrl } from 'kea-router'
import { getDefaultEventsSceneQuery } from 'scenes/events/defaults'
import { EventsQuery } from '~/queries/schema'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

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
    [Scene.WebAnalytics]: {
        projectBased: true,
        name: 'Web analytics',
        layout: 'app-container',
    },
    [Scene.Cohort]: {
        projectBased: true,
        name: 'Cohort',
    },
    [Scene.Events]: {
        projectBased: true,
        name: 'Event explorer',
    },
    [Scene.BatchExports]: {
        projectBased: true,
        name: 'Batch exports',
    },
    [Scene.BatchExportEdit]: {
        projectBased: true,
        name: 'Edit batch export',
    },
    [Scene.BatchExport]: {
        projectBased: true,
        name: 'Batch export',
    },
    [Scene.DataManagement]: {
        projectBased: true,
        name: 'Data management',
    },
    [Scene.EventDefinition]: {
        projectBased: true,
        name: 'Data management',
    },
    [Scene.PropertyDefinition]: {
        projectBased: true,
        name: 'Data management',
    },
    [Scene.Replay]: {
        projectBased: true,
        name: 'Session replay',
    },
    [Scene.ReplaySingle]: {
        projectBased: true,
        name: 'Replay recording',
    },
    [Scene.ReplayPlaylist]: {
        projectBased: true,
        name: 'Replay playlist',
    },
    [Scene.Person]: {
        projectBased: true,
        name: 'Person',
    },
    [Scene.PersonsManagement]: {
        projectBased: true,
        name: 'People & groups',
    },
    [Scene.Action]: {
        projectBased: true,
        name: 'Action',
    },
    [Scene.Group]: {
        projectBased: true,
        name: 'People & groups',
    },
    [Scene.Pipeline]: {
        projectBased: true,
        name: 'Pipeline',
    },
    [Scene.PipelineApp]: {
        projectBased: true,
        name: 'Pipeline app',
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
        name: 'Feature flags',
    },
    [Scene.FeatureFlag]: {
        projectBased: true,
    },
    [Scene.Surveys]: {
        projectBased: true,
        name: 'Surveys',
    },
    [Scene.Survey]: {
        projectBased: true,
        name: 'Survey',
    },
    [Scene.SurveyTemplates]: {
        projectBased: true,
        name: 'New survey',
    },
    [Scene.DataWarehouse]: {
        projectBased: true,
        name: 'Data warehouse',
    },
    [Scene.DataWarehousePosthog]: {
        projectBased: true,
        name: 'Data warehouse',
    },
    [Scene.DataWarehouseExternal]: {
        projectBased: true,
        name: 'Data warehouse',
    },
    [Scene.DataWarehouseSavedQueries]: {
        projectBased: true,
        name: 'Data warehouse',
    },
    [Scene.DataWarehouseSettings]: {
        projectBased: true,
        name: 'Data warehouse settings',
    },
    [Scene.DataWarehouseTable]: {
        projectBased: true,
        name: 'Data warehouse table',
    },
    [Scene.EarlyAccessFeatures]: {
        projectBased: true,
    },
    [Scene.EarlyAccessFeature]: {
        projectBased: true,
    },
    [Scene.Apps]: {
        projectBased: true,
        name: 'Apps',
    },
    [Scene.FrontendAppScene]: {
        projectBased: true,
        name: 'App',
    },
    [Scene.AppMetrics]: {
        projectBased: true,
        name: 'Apps',
    },
    [Scene.SavedInsights]: {
        projectBased: true,
        name: 'Product analytics',
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
        layout: 'plain',
    },
    [Scene.Onboarding]: {
        projectBased: true,
        layout: 'plain',
    },
    [Scene.ToolbarLaunch]: {
        projectBased: true,
        name: 'Launch toolbar',
    },
    [Scene.Site]: {
        projectBased: true,
        hideProjectNotice: true,
        layout: 'app-raw',
    },
    // Organization-based routes
    [Scene.OrganizationCreateFirst]: {
        name: 'Organization creation',
    },
    [Scene.OrganizationCreationConfirm]: {
        name: 'Confirm organization creation',
        onlyUnauthenticated: true,
    },
    [Scene.ProjectCreateFirst]: {
        name: 'Project creation',
        organizationBased: true,
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
        name: 'Instance status & settings',
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
    [Scene.Feedback]: {
        projectBased: true,
        name: 'Feedback',
    },
    [Scene.Notebook]: {
        projectBased: true,
        name: 'Notebook',
        layout: 'app-raw',
    },
    [Scene.Notebooks]: {
        projectBased: true,
        name: 'Notebooks',
    },
    [Scene.Canvas]: {
        projectBased: true,
        name: 'Canvas',
        layout: 'app-raw',
    },
    [Scene.Settings]: {
        projectBased: true,
        name: 'Settings',
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
    '/': preserveParams(urls.projectHomepage()),
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
    [urls.pipeline()]: Scene.Pipeline,
    // One entry for every available tab
    ...(Object.fromEntries(Object.values(PipelineTabs).map((tab) => [urls.pipeline(tab), Scene.Pipeline])) as Record<
        string,
        Scene
    >),
    // One entry for each available tab (key by app config id)
    ...(Object.fromEntries(
        Object.values(PipelineAppTabs).map((tab) => [urls.pipelineApp(':id', tab), Scene.PipelineApp])
    ) as Record<string, Scene>),
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
    [urls.dataWarehousePosthog()]: Scene.DataWarehousePosthog,
    [urls.dataWarehouseExternal()]: Scene.DataWarehouseExternal,
    [urls.dataWarehouseSavedQueries()]: Scene.DataWarehouseSavedQueries,
    [urls.dataWarehouseSettings()]: Scene.DataWarehouseSettings,
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
    [urls.verifyEmail()]: Scene.VerifyEmail,
    [urls.verifyEmail(':uuid')]: Scene.VerifyEmail,
    [urls.verifyEmail(':uuid', ':token')]: Scene.VerifyEmail,
    [urls.unsubscribe()]: Scene.Unsubscribe,
    [urls.integrationsRedirect(':kind')]: Scene.IntegrationsRedirect,
    [urls.debugQuery()]: Scene.DebugQuery,
    [urls.feedback()]: Scene.Feedback,
    [urls.feedback() + '/*']: Scene.Feedback,
    [urls.notebook(':shortId')]: Scene.Notebook,
    [urls.notebooks()]: Scene.Notebooks,
    [urls.canvas()]: Scene.Canvas,
    [urls.settings(':section' as any)]: Scene.Settings,
}

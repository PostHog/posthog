import { combineUrl } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { LoadedScene, Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { EventsQuery } from '~/queries/schema'
import { ActivityScope, InsightShortId, PipelineStage, PipelineTab, PropertyFilterType, ReplayTabs } from '~/types'

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
    [Scene.ErrorTracking]: {
        projectBased: true,
        name: 'Error tracking',
    },
    [Scene.ErrorTrackingGroup]: {
        projectBased: true,
        name: 'Error tracking group',
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
    [Scene.Activity]: {
        projectBased: true,
        name: 'Activity',
        defaultDocsPath: '/docs/data/events',
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
    [Scene.EventDefinitionEdit]: {
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
    [Scene.PropertyDefinitionEdit]: {
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
    [Scene.ReplayFilePlayback]: {
        projectBased: true,
        name: 'File playback',
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
    [Scene.PipelineNodeNew]: {
        projectBased: true,
        name: 'Pipeline new step',
        activityScope: ActivityScope.PLUGIN,
        defaultDocsPath: '/docs/cdp',
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
        hideBillingNotice: true,
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
    [Scene.Heatmaps]: {
        projectBased: true,
        name: 'Heatmaps',
    },
    [Scene.SessionAttributionExplorer]: {
        projectBased: true,
        name: 'Session attribution explorer (beta)',
    },
    [Scene.NotebookTest]: {
        projectBased: true,
        name: 'Notebook Test',
    },
}

// NOTE: These redirects will fully replace the URL. If you want to keep support for query and hash params then you should use the above `preserveParams` function.
export const redirects: Record<
    string,
    string | ((params: Params, searchParams: Params, hashParams: Params) => string)
> = {
    '/home': urls.projectHomepage(),
    '/saved_insights': urls.savedInsights(),
    '/dashboards': urls.dashboards(),
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
    '/recordings/file-playback': () => urls.replayFilePlayback(),
    '/recordings': (_params, _searchParams, hashParams) => {
        if (hashParams.sessionRecordingId) {
            // Previous URLs for an individual recording were like: /recordings/#sessionRecordingId=foobar
            return urls.replaySingle(hashParams.sessionRecordingId)
        }
        return urls.replay()
    },
    '/replay': urls.replay(),
    '/settings': urls.settings(),
    '/project/settings': urls.settings('project'),
    '/organization/settings': urls.settings('organization'),
    '/me/settings': urls.settings('user'),
    '/pipeline': urls.pipeline(),
    '/instance': urls.instanceStatus(),
    '/data-management/database': urls.pipeline(PipelineTab.Sources),
    '/pipeline/data-import': urls.pipeline(PipelineTab.Sources),
    '/batch_exports/:id': ({ id }) => urls.pipelineNode(PipelineStage.Destination, id),
    '/batch_exports': urls.pipeline(PipelineTab.Destinations),
    '/apps': urls.pipeline(PipelineTab.Overview),
    '/apps/:id': ({ id }) => urls.pipelineNode(PipelineStage.Transformation, id),
}

export const routes: Record<string, Scene> = {
    [urls.dashboards()]: Scene.Dashboards,
    [urls.dashboard(':id')]: Scene.Dashboard,
    [urls.dashboardTextTile(':id', ':textTileId')]: Scene.Dashboard,
    [urls.dashboardSharing(':id')]: Scene.Dashboard,
    [urls.dashboardSubcriptions(':id')]: Scene.Dashboard,
    [urls.dashboardSubcription(':id', ':subscriptionId')]: Scene.Dashboard,
    [urls.createAction()]: Scene.Action,
    [urls.duplicateAction(null)]: Scene.Action,
    [urls.action(':id')]: Scene.Action,
    [urls.ingestionWarnings()]: Scene.DataManagement,
    [urls.insightNew()]: Scene.Insight,
    [urls.insightEdit(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightView(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcriptions(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSubcription(':shortId' as InsightShortId, ':itemId')]: Scene.Insight,
    [urls.alert(':shortId' as InsightShortId, ':itemId')]: Scene.Insight,
    [urls.alerts(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.insightSharing(':shortId' as InsightShortId)]: Scene.Insight,
    [urls.savedInsights()]: Scene.SavedInsights,
    [urls.webAnalytics()]: Scene.WebAnalytics,
    [urls.actions()]: Scene.DataManagement,
    [urls.eventDefinitions()]: Scene.DataManagement,
    [urls.eventDefinition(':id')]: Scene.EventDefinition,
    [urls.eventDefinitionEdit(':id')]: Scene.EventDefinitionEdit,
    [urls.propertyDefinitions()]: Scene.DataManagement,
    [urls.propertyDefinition(':id')]: Scene.PropertyDefinition,
    [urls.propertyDefinitionEdit(':id')]: Scene.PropertyDefinitionEdit,
    [urls.dataManagementHistory()]: Scene.DataManagement,
    [urls.database()]: Scene.DataManagement,
    [urls.activity(':tab')]: Scene.Activity,
    [urls.events()]: Scene.Activity,
    [urls.replay()]: Scene.Replay,
    // One entry for every available tab
    ...Object.values(ReplayTabs).reduce((acc, tab) => {
        acc[urls.replay(tab)] = Scene.Replay
        return acc
    }, {} as Record<string, Scene>),
    [urls.replayFilePlayback()]: Scene.ReplayFilePlayback,
    [urls.replaySingle(':id')]: Scene.ReplaySingle,
    [urls.replayPlaylist(':id')]: Scene.ReplayPlaylist,
    [urls.personByDistinctId('*', false)]: Scene.Person,
    [urls.personByUUID('*', false)]: Scene.Person,
    [urls.persons()]: Scene.PersonsManagement,
    [urls.pipelineNodeNew(':stage')]: Scene.PipelineNodeNew,
    [urls.pipelineNodeNew(':stage', ':id')]: Scene.PipelineNodeNew,
    [urls.pipeline(':tab')]: Scene.Pipeline,
    [urls.pipelineNode(':stage', ':id', ':nodeTab')]: Scene.PipelineNode,
    [urls.pipelineNode(':stage', ':id')]: Scene.PipelineNode,
    [urls.groups(':groupTypeIndex')]: Scene.PersonsManagement,
    [urls.group(':groupTypeIndex', ':groupKey', false)]: Scene.Group,
    [urls.group(':groupTypeIndex', ':groupKey', false, ':groupTab')]: Scene.Group,
    [urls.cohort(':id')]: Scene.Cohort,
    [urls.cohorts()]: Scene.PersonsManagement,
    [urls.experiments()]: Scene.Experiments,
    [urls.experiment(':id')]: Scene.Experiment,
    [urls.earlyAccessFeatures()]: Scene.EarlyAccessFeatures,
    [urls.earlyAccessFeature(':id')]: Scene.EarlyAccessFeature,
    [urls.errorTracking()]: Scene.ErrorTracking,
    [urls.errorTrackingGroup(':fingerprint')]: Scene.ErrorTrackingGroup,
    [urls.surveys()]: Scene.Surveys,
    [urls.survey(':id')]: Scene.Survey,
    [urls.surveyTemplates()]: Scene.SurveyTemplates,
    [urls.dataWarehouse()]: Scene.DataWarehouse,
    [urls.dataWarehouseView(':id')]: Scene.DataWarehouse,
    [urls.dataWarehouseTable()]: Scene.DataWarehouseTable,
    [urls.dataWarehouseRedirect(':kind')]: Scene.DataWarehouseRedirect,
    [urls.featureFlags()]: Scene.FeatureFlags,
    [urls.featureFlag(':id')]: Scene.FeatureFlag,
    [urls.annotations()]: Scene.DataManagement,
    [urls.annotation(':id')]: Scene.DataManagement,
    [urls.projectHomepage()]: Scene.ProjectHomepage,
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
    [urls.notebook(':shortId')]: Scene.Notebook,
    [urls.notebooks()]: Scene.Notebooks,
    [urls.canvas()]: Scene.Canvas,
    [urls.settings(':section' as any)]: Scene.Settings,
    [urls.moveToPostHogCloud()]: Scene.MoveToPostHogCloud,
    [urls.heatmaps()]: Scene.Heatmaps,
    [urls.sessionAttributionExplorer()]: Scene.SessionAttributionExplorer,
    '/hogbooks': Scene.NotebookTest,
}

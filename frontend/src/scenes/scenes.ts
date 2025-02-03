import { combineUrl } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { LoadedScene, Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { productConfiguration, productRedirects, productRoutes } from '~/products'
import { EventsQuery } from '~/queries/schema'
import {
    ActivityScope,
    ActivityTab,
    InsightShortId,
    PipelineStage,
    PipelineTab,
    PropertyFilterType,
    ReplayTabs,
} from '~/types'

import { BillingSectionId } from './billing/types'

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

export const sceneConfigurations: Record<Scene | string, SceneConfig> = {
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
    [Scene.ErrorTrackingConfiguration]: {
        projectBased: true,
        name: 'Error tracking configuration',
    },
    [Scene.ErrorTrackingAlert]: {
        projectBased: true,
        name: 'Alert',
    },
    [Scene.ErrorTrackingIssue]: {
        projectBased: true,
        name: 'Error tracking issue',
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
    [Scene.WebAnalyticsWebVitals]: {
        projectBased: true,
        name: 'Web vitals',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics/web-vitals',
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
    [Scene.CustomCss]: {
        projectBased: true,
        name: 'Custom CSS',
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
        name: 'Experiments',
        defaultDocsPath: '/docs/experiments',
        activityScope: ActivityScope.EXPERIMENT,
    },
    [Scene.Experiment]: {
        projectBased: true,
        name: 'Experiment',
        defaultDocsPath: '/docs/experiments/creating-an-experiment',
        activityScope: ActivityScope.EXPERIMENT,
    },
    [Scene.ExperimentsSharedMetric]: {
        projectBased: true,
        name: 'Shared metric',
        defaultDocsPath: '/docs/experiments/creating-an-experiment',
        activityScope: ActivityScope.EXPERIMENT,
    },
    [Scene.ExperimentsSharedMetrics]: {
        projectBased: true,
        name: 'Shared metrics',
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
    [Scene.FeatureManagement]: {
        projectBased: true,
        name: 'Features',
        defaultDocsPath: '/docs/feature-flags',
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
    [Scene.SQLEditor]: {
        projectBased: true,
        name: 'SQL editor',
        defaultDocsPath: '/docs/data-warehouse/setup',
        layout: 'app-raw-no-header',
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
    [Scene.Max]: {
        projectBased: true,
        name: 'Max AI',
        layout: 'app-raw',
        hideProjectNotice: true, // FIXME: Currently doesn't render well...
    },
    [Scene.IntegrationsRedirect]: {
        name: 'Integrations redirect',
    },
    [Scene.Products]: {
        projectBased: true,
        hideProjectNotice: true,
        layout: 'app-raw',
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
    [Scene.BillingSection]: {
        name: 'Billing',
        hideProjectNotice: true,
        organizationBased: true,
    },
    [Scene.BillingAuthorizationStatus]: {
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
    [Scene.DebugHog]: {
        projectBased: true,
        name: 'Hog Repl',
    },
    [Scene.VerifyEmail]: {
        allowUnauthenticated: true,
        layout: 'plain',
    },
    [Scene.Notebook]: {
        projectBased: true,
        hideProjectNotice: true, // FIXME: Currently doesn't render well...
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
    ...productConfiguration,
}

// NOTE: These redirects will fully replace the URL. If you want to keep support for query and hash params then you should use a function (not string) redirect
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
    '/events': urls.activity(),
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
        return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
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
    '/replay/recent': (_params, searchParams) => {
        return urls.replay(undefined, searchParams.filters, searchParams.sessionRecordingId)
    },
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
    '/messaging': urls.messagingBroadcasts(),
    '/settings/organization-rbac': urls.settings('organization-roles'),
    ...productRedirects,
}

export const routes: Record<string, [Scene | string, string]> = {
    [urls.dashboards()]: [Scene.Dashboards, 'dashboards'],
    [urls.dashboard(':id')]: [Scene.Dashboard, 'dashboard'],
    [urls.dashboardTextTile(':id', ':textTileId')]: [Scene.Dashboard, 'dashboardTextTile'],
    [urls.dashboardSharing(':id')]: [Scene.Dashboard, 'dashboardSharing'],
    [urls.dashboardSubcriptions(':id')]: [Scene.Dashboard, 'dashboardSubcriptions'],
    [urls.dashboardSubcription(':id', ':subscriptionId')]: [Scene.Dashboard, 'dashboardSubcription'],
    [urls.createAction()]: [Scene.Action, 'createAction'],
    [urls.duplicateAction(null)]: [Scene.Action, 'duplicateAction'],
    [urls.action(':id')]: [Scene.Action, 'action'],
    [urls.ingestionWarnings()]: [Scene.DataManagement, 'ingestionWarnings'],
    [urls.insightNew()]: [Scene.Insight, 'insightNew'],
    [urls.insightEdit(':shortId' as InsightShortId)]: [Scene.Insight, 'insightEdit'],
    [urls.insightView(':shortId' as InsightShortId)]: [Scene.Insight, 'insightView'],
    [urls.insightSubcriptions(':shortId' as InsightShortId)]: [Scene.Insight, 'insightSubcriptions'],
    [urls.insightSubcription(':shortId' as InsightShortId, ':itemId')]: [Scene.Insight, 'insightSubcription'],
    [urls.alert(':shortId')]: [Scene.SavedInsights, 'alert'],
    [urls.alerts()]: [Scene.SavedInsights, 'alerts'],
    [urls.insightAlerts(':shortId' as InsightShortId)]: [Scene.Insight, 'insightAlerts'],
    [urls.insightSharing(':shortId' as InsightShortId)]: [Scene.Insight, 'insightSharing'],
    [urls.savedInsights()]: [Scene.SavedInsights, 'savedInsights'],
    [urls.webAnalytics()]: [Scene.WebAnalytics, 'webAnalytics'],
    [urls.webAnalyticsWebVitals()]: [Scene.WebAnalytics, 'webAnalyticsWebVitals'],
    [urls.revenue()]: [Scene.DataManagement, 'revenue'],
    [urls.actions()]: [Scene.DataManagement, 'actions'],
    [urls.eventDefinitions()]: [Scene.DataManagement, 'eventDefinitions'],
    [urls.eventDefinition(':id')]: [Scene.EventDefinition, 'eventDefinition'],
    [urls.eventDefinitionEdit(':id')]: [Scene.EventDefinitionEdit, 'eventDefinitionEdit'],
    [urls.propertyDefinitions()]: [Scene.DataManagement, 'propertyDefinitions'],
    [urls.propertyDefinition(':id')]: [Scene.PropertyDefinition, 'propertyDefinition'],
    [urls.propertyDefinitionEdit(':id')]: [Scene.PropertyDefinitionEdit, 'propertyDefinitionEdit'],
    [urls.dataManagementHistory()]: [Scene.DataManagement, 'dataManagementHistory'],
    [urls.database()]: [Scene.DataManagement, 'database'],
    [urls.activity(':tab')]: [Scene.Activity, 'activity'],
    [urls.replay()]: [Scene.Replay, 'replay'],
    // One entry for every available tab
    ...Object.values(ReplayTabs).reduce((acc, tab) => {
        acc[urls.replay(tab)] = [Scene.Replay, `replay:${tab}`]
        return acc
    }, {} as Record<string, [Scene, string]>),
    [urls.replayFilePlayback()]: [Scene.ReplayFilePlayback, 'replayFilePlayback'],
    [urls.replaySingle(':id')]: [Scene.ReplaySingle, 'replaySingle'],
    [urls.replayPlaylist(':id')]: [Scene.ReplayPlaylist, 'replayPlaylist'],
    [urls.personByDistinctId('*', false)]: [Scene.Person, 'personByDistinctId'],
    [urls.personByUUID('*', false)]: [Scene.Person, 'personByUUID'],
    [urls.persons()]: [Scene.PersonsManagement, 'persons'],
    [urls.pipelineNodeNew(':stage')]: [Scene.PipelineNodeNew, 'pipelineNodeNew'],
    [urls.pipelineNodeNew(':stage', ':id')]: [Scene.PipelineNodeNew, 'pipelineNodeNewWithId'],
    [urls.pipeline(':tab')]: [Scene.Pipeline, 'pipeline'],
    [urls.pipelineNode(':stage', ':id', ':nodeTab')]: [Scene.PipelineNode, 'pipelineNode'],
    [urls.pipelineNode(':stage', ':id')]: [Scene.PipelineNode, 'pipelineNodeWithId'],
    [urls.customCss()]: [Scene.CustomCss, 'customCss'],
    [urls.groups(':groupTypeIndex')]: [Scene.PersonsManagement, 'groups'],
    [urls.group(':groupTypeIndex', ':groupKey', false)]: [Scene.Group, 'group'],
    [urls.group(':groupTypeIndex', ':groupKey', false, ':groupTab')]: [Scene.Group, 'groupWithTab'],
    [urls.cohort(':id')]: [Scene.Cohort, 'cohort'],
    [urls.cohorts()]: [Scene.PersonsManagement, 'cohorts'],
    [urls.experiments()]: [Scene.Experiments, 'experiments'],
    [urls.experimentsSharedMetrics()]: [Scene.ExperimentsSharedMetrics, 'experimentsSharedMetrics'],
    [urls.experimentsSharedMetric(':id')]: [Scene.ExperimentsSharedMetric, 'experimentsSharedMetric'],
    [urls.experiment(':id')]: [Scene.Experiment, 'experiment'],
    [urls.errorTracking()]: [Scene.ErrorTracking, 'errorTracking'],
    [urls.errorTrackingConfiguration()]: [Scene.ErrorTrackingConfiguration, 'errorTrackingConfiguration'],
    [urls.errorTrackingAlert(':id')]: [Scene.ErrorTrackingAlert, 'errorTrackingAlert'],
    [urls.errorTrackingIssue(':id')]: [Scene.ErrorTrackingIssue, 'errorTrackingIssue'],
    [urls.surveys()]: [Scene.Surveys, 'surveys'],
    [urls.survey(':id')]: [Scene.Survey, 'survey'],
    [urls.surveyTemplates()]: [Scene.SurveyTemplates, 'surveyTemplates'],
    [urls.dataWarehouse()]: [Scene.DataWarehouse, 'dataWarehouse'],
    [urls.dataWarehouseView(':id')]: [Scene.DataWarehouse, 'dataWarehouseView'],
    [urls.dataWarehouseTable()]: [Scene.DataWarehouseTable, 'dataWarehouseTable'],
    [urls.dataWarehouseRedirect(':kind')]: [Scene.DataWarehouseRedirect, 'dataWarehouseRedirect'],
    [urls.sqlEditor()]: [Scene.SQLEditor, 'sqlEditor'],
    [urls.featureFlags()]: [Scene.FeatureFlags, 'featureFlags'],
    [urls.featureFlag(':id')]: [Scene.FeatureFlag, 'featureFlag'],
    [urls.featureManagement()]: [Scene.FeatureManagement, 'featureManagement'],
    [urls.featureManagement(':id')]: [Scene.FeatureManagement, 'featureManagementWithId'],
    [urls.annotations()]: [Scene.DataManagement, 'annotations'],
    [urls.annotation(':id')]: [Scene.DataManagement, 'annotation'],
    [urls.projectHomepage()]: [Scene.ProjectHomepage, 'projectHomepage'],
    [urls.max()]: [Scene.Max, 'max'],
    [urls.projectCreateFirst()]: [Scene.ProjectCreateFirst, 'projectCreateFirst'],
    [urls.organizationBilling()]: [Scene.Billing, 'organizationBilling'],
    [urls.organizationBillingSection(':section' as BillingSectionId)]: [
        Scene.BillingSection,
        'organizationBillingSection',
    ],
    [urls.billingAuthorizationStatus()]: [Scene.BillingAuthorizationStatus, 'billingAuthorizationStatus'],
    [urls.organizationCreateFirst()]: [Scene.OrganizationCreateFirst, 'organizationCreateFirst'],
    [urls.organizationCreationConfirm()]: [Scene.OrganizationCreationConfirm, 'organizationCreationConfirm'],
    [urls.instanceStatus()]: [Scene.SystemStatus, 'instanceStatus'],
    [urls.instanceSettings()]: [Scene.SystemStatus, 'instanceSettings'],
    [urls.instanceStaffUsers()]: [Scene.SystemStatus, 'instanceStaffUsers'],
    [urls.instanceKafkaInspector()]: [Scene.SystemStatus, 'instanceKafkaInspector'],
    [urls.instanceMetrics()]: [Scene.SystemStatus, 'instanceMetrics'],
    [urls.asyncMigrations()]: [Scene.AsyncMigrations, 'asyncMigrations'],
    [urls.asyncMigrationsFuture()]: [Scene.AsyncMigrations, 'asyncMigrationsFuture'],
    [urls.asyncMigrationsSettings()]: [Scene.AsyncMigrations, 'asyncMigrationsSettings'],
    [urls.deadLetterQueue()]: [Scene.DeadLetterQueue, 'deadLetterQueue'],
    [urls.toolbarLaunch()]: [Scene.ToolbarLaunch, 'toolbarLaunch'],
    [urls.site(':url')]: [Scene.Site, 'site'],
    [urls.login()]: [Scene.Login, 'login'],
    [urls.login2FA()]: [Scene.Login2FA, 'login2FA'],
    [urls.preflight()]: [Scene.PreflightCheck, 'preflight'],
    [urls.signup()]: [Scene.Signup, 'signup'],
    [urls.inviteSignup(':id')]: [Scene.InviteSignup, 'inviteSignup'],
    [urls.passwordReset()]: [Scene.PasswordReset, 'passwordReset'],
    [urls.passwordResetComplete(':uuid', ':token')]: [Scene.PasswordResetComplete, 'passwordResetComplete'],
    [urls.products()]: [Scene.Products, 'products'],
    [urls.onboarding(':productKey')]: [Scene.Onboarding, 'onboarding'],
    [urls.verifyEmail()]: [Scene.VerifyEmail, 'verifyEmail'],
    [urls.verifyEmail(':uuid')]: [Scene.VerifyEmail, 'verifyEmailWithUuid'],
    [urls.verifyEmail(':uuid', ':token')]: [Scene.VerifyEmail, 'verifyEmailWithToken'],
    [urls.unsubscribe()]: [Scene.Unsubscribe, 'unsubscribe'],
    [urls.integrationsRedirect(':kind')]: [Scene.IntegrationsRedirect, 'integrationsRedirect'],
    [urls.debugQuery()]: [Scene.DebugQuery, 'debugQuery'],
    [urls.debugHog()]: [Scene.DebugHog, 'debugHog'],
    [urls.notebook(':shortId')]: [Scene.Notebook, 'notebook'],
    [urls.notebooks()]: [Scene.Notebooks, 'notebooks'],
    [urls.canvas()]: [Scene.Canvas, 'canvas'],
    [urls.settings(':section' as any)]: [Scene.Settings, 'settings'],
    [urls.moveToPostHogCloud()]: [Scene.MoveToPostHogCloud, 'moveToPostHogCloud'],
    [urls.heatmaps()]: [Scene.Heatmaps, 'heatmaps'],
    [urls.sessionAttributionExplorer()]: [Scene.SessionAttributionExplorer, 'sessionAttributionExplorer'],
    ...productRoutes,
}

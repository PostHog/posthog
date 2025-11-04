import { combineUrl } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { Params, Scene, SceneConfig, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorAccessDenied as ErrorAccessDeniedComponent } from '~/layout/ErrorAccessDenied'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { productConfiguration, productRedirects, productRoutes } from '~/products'
import { EventsQuery } from '~/queries/schema/schema-general'
import { ActivityScope, ActivityTab, InsightShortId, PropertyFilterType, ReplayTabs } from '~/types'

import { BillingSectionId } from './billing/types'
import { DataPipelinesSceneTab } from './data-pipelines/DataPipelinesScene'

export const emptySceneParams = { params: {}, searchParams: {}, hashParams: {} }

export const preloadedScenes: Record<string, SceneExport> = {
    [Scene.Error404]: {
        component: Error404Component,
    },
    [Scene.ErrorAccessDenied]: {
        component: ErrorAccessDeniedComponent,
    },
    [Scene.ErrorNetwork]: {
        component: ErrorNetworkComponent,
    },
    [Scene.ErrorProjectUnavailable]: {
        component: ErrorProjectUnavailableComponent,
    },
}

export const sceneConfigurations: Record<Scene | string, SceneConfig> = {
    [Scene.AdvancedActivityLogs]: {
        projectBased: true,
        organizationBased: false,
        name: 'Activity logs',
        description:
            'Track all changes and activities in your organization with detailed filtering and export capabilities.',
    },
    [Scene.AsyncMigrations]: { instanceLevel: true },
    [Scene.Annotations]: {
        projectBased: true,
        name: 'Annotations',
        description:
            'Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics.',
        iconType: 'annotation',
    },
    [Scene.BillingAuthorizationStatus]: {
        hideProjectNotice: true,
        organizationBased: true,
        defaultDocsPath: '/pricing',
    },
    [Scene.BillingSection]: { name: 'Billing', hideProjectNotice: true, organizationBased: true },
    [Scene.Billing]: { hideProjectNotice: true, organizationBased: true, defaultDocsPath: '/pricing' },
    [Scene.Canvas]: {
        projectBased: true,
        name: 'Canvas',
        description: 'You can change anything you like and it is persisted to the URL for easy sharing.',
        layout: 'app-full-scene-height',
        defaultDocsPath: '/blog/introducing-notebooks',
        hideProjectNotice: true,
    },
    [Scene.CLIAuthorize]: {
        name: 'Authorize CLI',
        projectBased: false,
        organizationBased: false,
        layout: 'plain',
    },
    [Scene.Cohort]: { projectBased: true, name: 'Cohort', defaultDocsPath: '/docs/data/cohorts' },
    [Scene.CohortCalculationHistory]: { projectBased: true, name: 'Cohort Calculation History' },
    [Scene.Cohorts]: {
        projectBased: true,
        name: 'Cohorts',
        description: 'A catalog of identified persons and your created cohorts.',
        defaultDocsPath: '/docs/data/cohorts',
        iconType: 'cohort',
    },
    [Scene.Comments]: {
        projectBased: true,
        name: 'Comments',
        description: 'Comments allow you to provide context and discussions on various elements in PostHog.',
        iconType: 'comment',
    },
    [Scene.CustomerAnalytics]: { projectBased: true, name: 'Customer analytics' },
    [Scene.Dashboard]: {
        projectBased: true,
        activityScope: ActivityScope.DASHBOARD,
        defaultDocsPath: '/docs/product-analytics/dashboards',
        iconType: 'dashboard',
    },
    [Scene.Dashboards]: {
        projectBased: true,
        name: 'Dashboards',
        activityScope: ActivityScope.DASHBOARD,
        description: 'Create and manage your dashboards',
        iconType: 'dashboard',
    },
    [Scene.DataManagement]: {
        projectBased: true,
        name: 'Data management',
        defaultDocsPath: '/docs/data',
    },

    [Scene.DataPipelines]: {
        name: 'Data pipelines',
        description: 'Ingest, transform, and send data between hundreds of tools.',
        activityScope: ActivityScope.HOG_FUNCTION,
        defaultDocsPath: '/docs/cdp',
        iconType: 'data_pipeline',
    },
    [Scene.DataPipelinesNew]: {
        projectBased: true,
        name: 'New data pipeline',
        activityScope: ActivityScope.HOG_FUNCTION,
        defaultDocsPath: '/docs/cdp',
    },
    [Scene.DataWarehouseSource]: {
        projectBased: true,
        name: 'Data warehouse source',
        defaultDocsPath: '/docs/cdp/sources',
    },
    [Scene.DataWarehouseSourceNew]: {
        projectBased: true,
        name: 'New data warehouse source',
        defaultDocsPath: async () => {
            try {
                // Importing here to avoid problems with importing logics from such a global file like this one
                const { sourceWizardLogic } = await import('./data-warehouse/new/sourceWizardLogic')
                const logic = sourceWizardLogic.findMounted()

                if (logic) {
                    const { selectedConnector } = logic.values

                    // `docsUrl` includes the full URL, we only need the pathname when opening docs in the sidepanel
                    if (selectedConnector?.docsUrl) {
                        const parsedUrl = new URL(selectedConnector.docsUrl)
                        return parsedUrl.pathname
                    }
                }
            } catch (error) {
                console.error('Failed to get default docs path for new data warehouse source', error)
            }

            return '/docs/cdp/sources'
        },
    },
    [Scene.DeadLetterQueue]: { instanceLevel: true },
    [Scene.DebugHog]: { projectBased: true, name: 'Hog Repl' },
    [Scene.DebugQuery]: { projectBased: true },
    [Scene.Error404]: { name: 'Not found', projectBased: true },
    [Scene.ErrorAccessDenied]: { name: 'Access denied' },
    [Scene.ErrorNetwork]: { name: 'Network error' },
    [Scene.ErrorProjectUnavailable]: { name: 'Project unavailable' },
    [Scene.EventDefinitionEdit]: {
        projectBased: true,
        name: 'Data management',
        activityScope: ActivityScope.EVENT_DEFINITION,
        defaultDocsPath: '/docs/data/events',
    },
    [Scene.EventDefinitions]: {
        projectBased: true,
        name: 'Event definitions',
        activityScope: ActivityScope.EVENT_DEFINITION,
        defaultDocsPath: '/docs/data/events',
        description: 'Event definitions are a way to define events that can be used in your app or website.',
    },
    [Scene.EventDefinition]: {
        projectBased: true,
        name: 'Event definitions',
        activityScope: ActivityScope.EVENT_DEFINITION,
        defaultDocsPath: '/docs/data/events',
        iconType: 'event_definition',
    },
    [Scene.Experiment]: {
        projectBased: true,
        name: 'Experiment',
        defaultDocsPath: '/docs/experiments/creating-an-experiment',
        activityScope: ActivityScope.EXPERIMENT,
        iconType: 'experiment',
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
    [Scene.Experiments]: {
        projectBased: true,
        name: 'Experiments',
        defaultDocsPath: '/docs/experiments',
        activityScope: ActivityScope.EXPERIMENT,
        description:
            'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.',
        iconType: 'experiment',
    },
    [Scene.ExploreEvents]: {
        projectBased: true,
        name: 'Explore events',
        defaultDocsPath: '/docs/data/events',
        description: 'A catalog of all user interactions with your app or website.',
        iconType: 'event',
    },
    [Scene.FeatureFlag]: {
        projectBased: true,
        activityScope: ActivityScope.FEATURE_FLAG,
        defaultDocsPath: '/docs/feature-flags/creating-feature-flags',
    },
    [Scene.FeatureFlags]: {
        projectBased: true,
        name: 'Feature flags',
        description:
            'Use feature flags to safely deploy and roll back new features in an easy-to-manage way. Roll variants out to certain groups, a percentage of users, or everyone all at once.',
        defaultDocsPath: '/docs/feature-flags',
        activityScope: ActivityScope.FEATURE_FLAG,
    },
    [Scene.Game368]: { name: '368 Hedgehogs', projectBased: true },
    [Scene.Group]: {
        projectBased: true,
        name: 'People & groups',
        defaultDocsPath: '/docs/product-analytics/group-analytics',
    },
    [Scene.GroupsNew]: { projectBased: true, defaultDocsPath: '/docs/product-analytics/group-analytics' },
    [Scene.Groups]: { projectBased: true, name: 'Groups', defaultDocsPath: '/docs/product-analytics/group-analytics' },
    [Scene.Heatmaps]: {
        projectBased: true,
        name: 'Heatmaps',
        iconType: 'heatmap',
        description: 'Heatmaps are a way to visualize user behavior on your website.',
    },
    [Scene.Heatmap]: {
        projectBased: true,
        name: 'Heatmap',
        iconType: 'heatmap',
    },
    [Scene.HeatmapNew]: {
        projectBased: true,
        name: 'New heatmap',
        iconType: 'heatmap',
    },
    [Scene.HeatmapRecording]: {
        projectBased: true,
        name: 'Heatmap recording',
        iconType: 'heatmap',
    },
    [Scene.HogFunction]: { projectBased: true, name: 'Hog function', activityScope: ActivityScope.HOG_FUNCTION },
    [Scene.Insight]: {
        projectBased: true,
        name: 'Insights',
        activityScope: ActivityScope.INSIGHT,
        defaultDocsPath: '/docs/product-analytics/insights',
    },
    [Scene.IntegrationsRedirect]: { name: 'Integrations redirect' },
    [Scene.IngestionWarnings]: {
        projectBased: true,
        name: 'Ingestion warnings',
        defaultDocsPath: '/docs/data/ingestion-warnings',
        iconType: 'ingestion_warning',
        description: 'Data ingestion related warnings from past 30 days.',
    },
    [Scene.InviteSignup]: { allowUnauthenticated: true, layout: 'plain' },
    [Scene.LegacyPlugin]: { projectBased: true, name: 'Legacy plugin' },
    [Scene.LennyCoupon]: { name: "Lenny's Newsletter", organizationBased: true, layout: 'app-container' },
    [Scene.Link]: { projectBased: true },
    [Scene.Links]: { projectBased: true, name: 'Links' },
    [Scene.LiveEvents]: {
        projectBased: true,
        name: 'Live events',
        defaultDocsPath: '/docs/data/events',
        description: 'Real-time events from your app or website.',
        iconType: 'live',
    },
    [Scene.LiveDebugger]: { projectBased: true, name: 'Live debugger', defaultDocsPath: '/docs/data/events' },
    [Scene.Login2FA]: { onlyUnauthenticated: true },
    [Scene.EmailMFAVerify]: { onlyUnauthenticated: true },
    [Scene.Login]: { onlyUnauthenticated: true },
    [Scene.Max]: { projectBased: true, name: 'Max', layout: 'app-raw', hideProjectNotice: true },
    [Scene.MoveToPostHogCloud]: { name: 'Move to PostHog Cloud', hideProjectNotice: true },
    [Scene.NewTab]: { projectBased: true, name: 'New tab', hideProjectNotice: true, layout: 'app-raw' },
    [Scene.Notebook]: {
        projectBased: true,
        name: 'Notebook',
        activityScope: ActivityScope.NOTEBOOK,
        defaultDocsPath: '/blog/introducing-notebooks',
        canvasBackground: true,
    },
    [Scene.Notebooks]: {
        projectBased: true,
        name: 'Notebooks',
        description: 'Notebooks are a way to organize your work and share it with others.',
        activityScope: ActivityScope.NOTEBOOK,
        defaultDocsPath: '/blog/introducing-notebooks',
    },
    [Scene.OAuthAuthorize]: {
        name: 'Authorize',
        layout: 'plain',
        projectBased: false,
        organizationBased: false,
        allowUnauthenticated: true,
    },
    [Scene.Onboarding]: { projectBased: true, name: 'Onboarding', layout: 'plain' },
    [Scene.OrganizationCreateFirst]: {
        name: 'Organization creation',
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    [Scene.OrganizationCreationConfirm]: {
        name: 'Confirm organization creation',
        onlyUnauthenticated: true,
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    [Scene.PasswordResetComplete]: { onlyUnauthenticated: true },
    [Scene.PasswordReset]: { onlyUnauthenticated: true },
    [Scene.Person]: {
        projectBased: true,
        name: 'People',
        activityScope: ActivityScope.PERSON,
        defaultDocsPath: '/docs/data/persons',
        iconType: 'user',
    },
    [Scene.Persons]: {
        projectBased: true,
        name: 'Persons',
        description: 'A catalog of all the people behind your events',
        activityScope: ActivityScope.PERSON,
        defaultDocsPath: '/docs/data/persons',
        iconType: 'persons',
    },
    [Scene.PreflightCheck]: { onlyUnauthenticated: true },
    [Scene.Products]: { projectBased: true, name: 'Products', layout: 'plain' },
    [Scene.ProjectCreateFirst]: {
        name: 'Project creation',
        organizationBased: true,
        defaultDocsPath: '/docs/data/organizations-and-projects',
    },
    [Scene.ProjectHomepage]: {
        projectBased: true,
        name: 'Homepage',
        layout: 'app-raw',
    },
    [Scene.PropertyDefinitionEdit]: {
        projectBased: true,
        name: 'Data management',
        activityScope: ActivityScope.PROPERTY_DEFINITION,
    },
    [Scene.PropertyDefinitions]: {
        projectBased: true,
        name: 'Property definitions',
        activityScope: ActivityScope.PROPERTY_DEFINITION,
        iconType: 'property_definition',
        description: 'Properties are additional fields you can configure to be sent along with an event capture.',
    },
    [Scene.PropertyDefinition]: {
        projectBased: true,
        name: 'Property definitions',
        activityScope: ActivityScope.PROPERTY_DEFINITION,
        iconType: 'property_definition',
        description: 'Properties are additional fields you can configure to be sent along with an event capture.',
    },
    [Scene.ReplayFilePlayback]: {
        projectBased: true,
        name: 'File playback',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.ReplayPlaylist]: {
        projectBased: true,
        name: 'Replay playlist',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.ReplaySettings]: {
        projectBased: true,
        name: 'Settings',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.ReplaySingle]: {
        projectBased: true,
        name: 'Replay recording',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
    },
    [Scene.Replay]: {
        projectBased: true,
        name: 'Session replay',
        activityScope: ActivityScope.REPLAY,
        defaultDocsPath: '/docs/session-replay',
        layout: 'app-full-scene-height',
        iconType: 'session_replay',
        description:
            'Replay recordings of user sessions to understand how users interact with your product or website.',
    },
    [Scene.RevenueAnalytics]: {
        projectBased: true,
        name: 'Revenue analytics',
        layout: 'app-container',
        defaultDocsPath: '/docs/revenue-analytics',
    },
    [Scene.SQLEditor]: {
        projectBased: true,
        name: 'SQL editor',
        defaultDocsPath: '/docs/cdp/sources',
        layout: 'app-raw-no-header',
        hideProjectNotice: true,
        description: 'Write and execute SQL queries against your data warehouse',
    },
    [Scene.SavedInsights]: {
        projectBased: true,
        name: 'Product analytics',
        description: 'Track, analyze, and experiment with user behavior.',
        activityScope: ActivityScope.INSIGHT,
        defaultDocsPath: '/docs/product-analytics',
        iconType: 'product_analytics',
    },
    [Scene.SessionAttributionExplorer]: { projectBased: true, name: 'Session attribution explorer (beta)' },
    [Scene.Settings]: { projectBased: true, name: 'Settings' },
    [Scene.Signup]: { onlyUnauthenticated: true },
    [Scene.Site]: { projectBased: true, hideProjectNotice: true, layout: 'app-raw' },
    [Scene.StartupProgram]: { name: 'PostHog for Startups', organizationBased: true, layout: 'app-container' },
    [Scene.SurveyTemplates]: {
        projectBased: true,
        name: 'New survey',
        defaultDocsPath: '/docs/surveys/creating-surveys',
    },
    [Scene.Survey]: {
        projectBased: true,
        name: 'Survey',
        defaultDocsPath: '/docs/surveys',
        activityScope: ActivityScope.SURVEY,
    },
    [Scene.Surveys]: {
        projectBased: true,
        name: 'Surveys',
        defaultDocsPath: '/docs/surveys',
        activityScope: ActivityScope.SURVEY,
        description: 'Create surveys to collect feedback from your users',
        iconType: 'survey',
    },
    [Scene.SystemStatus]: { instanceLevel: true, name: 'Instance panel' },
    [Scene.ToolbarLaunch]: { projectBased: true, name: 'Launch toolbar', defaultDocsPath: '/docs/toolbar' },
    [Scene.Unsubscribe]: { allowUnauthenticated: true, layout: 'app-raw' },
    [Scene.VerifyEmail]: { allowUnauthenticated: true, layout: 'plain' },
    [Scene.WebAnalyticsMarketing]: {
        projectBased: true,
        name: 'Marketing settings',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics/marketing',
        description: 'Analyze your marketing analytics data to understand your marketing performance.',
        iconType: 'marketing_settings',
    },
    [Scene.WebAnalyticsPageReports]: {
        projectBased: true,
        name: 'Page reports',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics',
    },
    [Scene.WebAnalyticsWebVitals]: {
        projectBased: true,
        name: 'Web vitals',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics/web-vitals',
    },
    [Scene.WebAnalytics]: {
        projectBased: true,
        name: 'Web analytics',
        layout: 'app-container',
        defaultDocsPath: '/docs/web-analytics',
        description: 'Analyze your web analytics data to understand website performance and user behavior.',
        iconType: 'web_analytics',
    },
    [Scene.Wizard]: { projectBased: true, name: 'Wizard', layout: 'plain' },
    ...productConfiguration,
}

const redirectPipeline = (stage: DataPipelinesSceneTab, id: string): string => {
    if (id.startsWith('hog-')) {
        return urls.hogFunction(id.replace('hog-', ''))
    }
    return urls.dataPipelines(stage)
}

// NOTE: These redirects will fully replace the URL. If you want to keep support for query and hash params then you should use a function (not string) redirect
// NOTE: If you need a query param to be automatically forwarded to the redirect URL, add it to the forwardedRedirectQueryParams array
export const forwardedRedirectQueryParams: string[] = ['invite_modal']
export const redirects: Record<
    string,
    string | ((params: Params, searchParams: Params, hashParams: Params) => string)
> = {
    '/action': urls.createAction(),
    '/action/:id': ({ id }) => urls.action(id),
    '/actions': urls.actions(),
    '/activity': urls.activity(),
    '/annotations': () => urls.annotations(),
    '/annotations/:id': ({ id }) => urls.annotation(id),
    '/apps': urls.dataPipelines('overview'),
    '/apps/:id': urls.dataPipelines('overview'),
    '/batch_exports/:id': ({ id }) => urls.batchExport(id),
    '/batch_exports': urls.dataPipelines('destinations'),
    '/comments': () => urls.comments(),
    '/dashboards': urls.dashboards(),
    '/data-management': urls.eventDefinitions(),
    '/data-management/database': urls.dataPipelines('sources'),
    '/data-pipelines': urls.dataPipelines('overview'),
    '/data-warehouse': urls.dataWarehouse(),
    '/data-warehouse/sources/:id': ({ id }) => urls.dataWarehouseSource(id, 'schemas'),

    '/events': urls.activity(),
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
            const after = dayjs(timestamp).subtract(15, 'second').startOf('second').toISOString()
            const before = dayjs(timestamp).add(15, 'second').startOf('second').toISOString()
            Object.assign(query.source as EventsQuery, { before, after })
        } catch {
            lemonToast.error('Invalid event timestamp')
        }
        return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
    },

    '/events/actions': urls.actions(),
    '/events/properties': urls.propertyDefinitions(),
    '/events/properties/:id': ({ id }) => urls.propertyDefinition(id),
    '/events/stats': urls.eventDefinitions(),
    '/events/stats/:id': ({ id }) => urls.eventDefinition(id),
    '/home': urls.projectHomepage(),
    '/i/:shortId': ({ shortId }) => urls.insightView(shortId),
    '/instance': urls.instanceStatus(),
    '/me/settings': urls.settings('user'),
    '/new': urls.newTab(),
    '/live-debugger': urls.liveDebugger(),
    '/organization/members': urls.settings('organization'),
    '/organization/settings': urls.settings('organization'),
    '/pipeline': urls.dataPipelines('overview'),
    '/pipelines': urls.dataPipelines('overview'),
    '/pipeline/new/site-app': urls.dataPipelinesNew('site_app'),
    '/pipeline/sources/:id': ({ id }) => redirectPipeline('sources', id),
    '/pipeline/destinations/:id': ({ id }) => redirectPipeline('destinations', id),
    '/pipeline/transformations/:id': ({ id }) => redirectPipeline('transformations', id),
    '/pipeline/sources/:id/:tab': ({ id }) => redirectPipeline('sources', id),
    '/pipeline/destinations/:id/:tab': ({ id }) => redirectPipeline('destinations', id),
    '/pipeline/site-apps/:id/:tab': ({ id }) => redirectPipeline('site_apps', id),
    '/pipeline/transformations/:id/:tab': ({ id }) => redirectPipeline('transformations', id),
    '/pipeline/data-import': urls.dataPipelines('sources'),
    '/project/settings': urls.settings('project'),
    '/recordings/file-playback': () => urls.replayFilePlayback(),
    '/recordings/playlists/:id': ({ id }) => urls.replayPlaylist(id),
    '/recordings/settings': () => urls.replaySettings(),
    '/recordings/:id': ({ id }) => urls.replaySingle(id),
    '/recordings': (_params, _searchParams, hashParams) => {
        if (hashParams.sessionRecordingId) {
            // Previous URLs for an individual recording were like: /recordings/#sessionRecordingId=foobar
            return urls.replaySingle(hashParams.sessionRecordingId)
        }
        return urls.replay()
    },
    '/replay': urls.replay(),
    '/replay/recent': (_params, searchParams) =>
        urls.replay(undefined, searchParams.filters, searchParams.sessionRecordingId),
    '/saved_insights': urls.savedInsights(),
    '/settings': urls.settings(),
    '/settings/organization-rbac': urls.settings('organization-roles'),
    ...productRedirects,
}

export const routes: Record<string, [Scene | string, string]> = {
    [urls.newTab()]: [Scene.NewTab, 'newTab'],
    [urls.dashboards()]: [Scene.Dashboards, 'dashboards'],
    [urls.dashboard(':id')]: [Scene.Dashboard, 'dashboard'],
    [urls.dashboardTextTile(':id', ':textTileId')]: [Scene.Dashboard, 'dashboardTextTile'],
    [urls.dashboardSharing(':id')]: [Scene.Dashboard, 'dashboardSharing'],
    [urls.dashboardSubscriptions(':id')]: [Scene.Dashboard, 'dashboardSubscriptions'],
    [urls.dashboardSubscription(':id', ':subscriptionId')]: [Scene.Dashboard, 'dashboardSubscription'],
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
    [urls.webAnalyticsMarketing()]: [Scene.WebAnalytics, 'webAnalyticsMarketing'],
    [urls.webAnalyticsPageReports()]: [Scene.WebAnalytics, 'webAnalyticsPageReports'],
    [urls.revenueAnalytics()]: [Scene.RevenueAnalytics, 'revenueAnalytics'],
    [urls.revenueSettings()]: [Scene.DataManagement, 'revenue'],
    [urls.marketingAnalytics()]: [Scene.DataManagement, 'marketingAnalytics'],
    [urls.dataWarehouseManagedViewsets()]: [Scene.DataManagement, 'dataWarehouseManagedViewsets'],
    [urls.eventDefinitions()]: [Scene.DataManagement, 'eventDefinitions'],
    [urls.eventDefinition(':id')]: [Scene.EventDefinition, 'eventDefinition'],
    [urls.eventDefinitionEdit(':id')]: [Scene.EventDefinitionEdit, 'eventDefinitionEdit'],
    [urls.propertyDefinitions()]: [Scene.DataManagement, 'propertyDefinitions'],
    [urls.propertyDefinition(':id')]: [Scene.PropertyDefinition, 'propertyDefinition'],
    [urls.propertyDefinitionEdit(':id')]: [Scene.PropertyDefinitionEdit, 'propertyDefinitionEdit'],
    [urls.schemaManagement()]: [Scene.DataManagement, 'schemaManagement'],
    [urls.dataManagementHistory()]: [Scene.DataManagement, 'dataManagementHistory'],
    [urls.database()]: [Scene.DataManagement, 'database'],
    [urls.activity(ActivityTab.ExploreEvents)]: [Scene.ExploreEvents, 'exploreEvents'],
    [urls.activity(ActivityTab.LiveEvents)]: [Scene.LiveEvents, 'liveEvents'],
    [urls.replay()]: [Scene.Replay, 'replay'],
    // One entry for every available tab
    ...Object.values(ReplayTabs).reduce(
        (acc, tab) => {
            acc[urls.replay(tab)] = [Scene.Replay, `replay:${tab}`]
            return acc
        },
        {} as Record<string, [Scene, string]>
    ),
    [urls.replayFilePlayback()]: [Scene.ReplayFilePlayback, 'replayFilePlayback'],
    [urls.replaySingle(':id')]: [Scene.ReplaySingle, 'replaySingle'],
    [urls.replayPlaylist(':id')]: [Scene.ReplayPlaylist, 'replayPlaylist'],
    [urls.replaySettings()]: [Scene.ReplaySettings, 'replaySettings'],
    [urls.personByDistinctId('*', false)]: [Scene.Person, 'personByDistinctId'],
    [urls.personByUUID('*', false)]: [Scene.Person, 'personByUUID'],
    [urls.persons()]: [Scene.Persons, 'persons'],
    [urls.customCss()]: [Scene.CustomCss, 'customCss'],
    [urls.groups(':groupTypeIndex')]: [Scene.Groups, 'groups'],
    [urls.groupsNew(':groupTypeIndex')]: [Scene.GroupsNew, 'groupsNew'],
    [urls.group(':groupTypeIndex', ':groupKey', false)]: [Scene.Group, 'group'],
    [urls.group(':groupTypeIndex', ':groupKey', false, ':groupTab')]: [Scene.Group, 'groupWithTab'],
    [urls.cohort(':id')]: [Scene.Cohort, 'cohort'],
    [urls.cohortCalculationHistory(':id')]: [Scene.CohortCalculationHistory, 'cohortCalculationHistory'],
    [urls.cohorts()]: [Scene.Cohorts, 'cohorts'],
    [urls.experiments()]: [Scene.Experiments, 'experiments'],
    [urls.experimentsSharedMetrics()]: [Scene.ExperimentsSharedMetrics, 'experimentsSharedMetrics'],
    [urls.experimentsSharedMetric(':id')]: [Scene.ExperimentsSharedMetric, 'experimentsSharedMetric'],
    [urls.experimentsSharedMetric(':id', ':action')]: [Scene.ExperimentsSharedMetric, 'experimentsSharedMetric'],
    [urls.experiment(':id')]: [Scene.Experiment, 'experiment'],
    [urls.experiment(':id', ':formMode')]: [Scene.Experiment, 'experiment'],
    [urls.surveys()]: [Scene.Surveys, 'surveys'],
    [urls.survey(':id')]: [Scene.Survey, 'survey'],
    [urls.surveyTemplates()]: [Scene.SurveyTemplates, 'surveyTemplates'],
    [urls.sqlEditor()]: [Scene.SQLEditor, 'sqlEditor'],
    [urls.featureFlags()]: [Scene.FeatureFlags, 'featureFlags'],
    [urls.featureFlag(':id')]: [Scene.FeatureFlag, 'featureFlag'],
    [urls.annotations()]: [Scene.DataManagement, 'annotations'],
    [urls.annotation(':id')]: [Scene.DataManagement, 'annotation'],
    [urls.comments()]: [Scene.DataManagement, 'comments'],
    [urls.projectHomepage()]: [Scene.ProjectHomepage, 'projectHomepage'],
    [urls.maxHistory()]: [Scene.Max, 'maxHistory'],
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
    [urls.cliAuthorize()]: [Scene.CLIAuthorize, 'cliAuthorize'],
    [urls.emailMFAVerify()]: [Scene.EmailMFAVerify, 'emailMFAVerify'],
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
    [urls.advancedActivityLogs()]: [Scene.AdvancedActivityLogs, 'advancedActivityLogs'],
    [urls.heatmaps()]: [Scene.Heatmaps, 'heatmaps'],
    [urls.heatmapNew()]: [Scene.HeatmapNew, 'heatmapNew'],
    [urls.heatmapRecording()]: [Scene.HeatmapRecording, 'heatmapRecording'],
    [urls.heatmap(':id')]: [Scene.Heatmap, 'heatmap'],
    [urls.liveDebugger()]: [Scene.LiveDebugger, 'liveDebugger'],
    [urls.links()]: [Scene.Links, 'links'],
    [urls.link(':id')]: [Scene.Link, 'link'],
    [urls.sessionAttributionExplorer()]: [Scene.SessionAttributionExplorer, 'sessionAttributionExplorer'],
    [urls.wizard()]: [Scene.Wizard, 'wizard'],
    [urls.lenny()]: [Scene.LennyCoupon, 'lenny'],
    [urls.startups()]: [Scene.StartupProgram, 'startupProgram'],
    [urls.startups(':referrer')]: [Scene.StartupProgram, 'startupProgramWithReferrer'],
    [urls.oauthAuthorize()]: [Scene.OAuthAuthorize, 'oauthAuthorize'],
    [urls.dataPipelines(':kind' as any)]: [Scene.DataPipelines, 'dataPipelines'],
    [urls.dataPipelinesNew(':kind' as any)]: [Scene.DataPipelinesNew, 'dataPipelinesNew'],
    [urls.dataWarehouse()]: [Scene.DataWarehouse, 'dataWarehouse'],
    [urls.dataWarehouseSourceNew()]: [Scene.DataWarehouseSourceNew, 'dataWarehouseSourceNew'],
    [urls.dataWarehouseSource(':id', ':tab' as any)]: [Scene.DataWarehouseSource, 'dataWarehouseSource'],
    [urls.batchExportNew(':service')]: [Scene.BatchExportNew, 'batchExportNew'],
    [urls.batchExport(':id')]: [Scene.BatchExport, 'batchExport'],
    [urls.legacyPlugin(':id')]: [Scene.LegacyPlugin, 'legacyPlugin'],
    [urls.hogFunction(':id')]: [Scene.HogFunction, 'hogFunction'],
    [urls.hogFunctionNew(':templateId')]: [Scene.HogFunction, 'hogFunctionNew'],
    ...productRoutes,
}

import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import posthog from 'posthog-js'
import React from 'react'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { featureFlagsLogic, type FeatureFlagsResult } from 'scenes/feature-flags/featureFlagsLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { EventDefinitionType, type Experiment, PipelineStage, ProductKey, ReplayTabs, TeamBasicType } from '~/types'

import { sidePanelSettingsLogic } from '../sidePanelSettingsLogic'
import type { activationLogicType } from './activationLogicType'

export enum ActivationTask {
    IngestFirstEvent = 'ingest_first_event',
    InviteTeamMember = 'invite_team_member',
    CreateFirstInsight = 'create_first_insight',
    CreateFirstDashboard = 'create_first_dashboard',
    TrackCustomEvents = 'track_custom_events',
    SetUpReverseProxy = 'set_up_reverse_proxy',

    // Session Replay
    SetupSessionRecordings = 'setup_session_recordings',
    WatchSessionRecording = 'watch_session_recording',

    // Feature Flags
    CreateFeatureFlag = 'create_feature_flag',

    // Experiments
    LaunchExperiment = 'launch_experiment',

    // Data Pipelines
    ConnectSource = 'connect_source',
    ConnectDestination = 'connect_destination',

    // Surveys
    LaunchSurvey = 'launch_survey',
    CollectSurveyResponses = 'collect_survey_responses',
}

export enum ActivationSection {
    QuickStart = 'quick_start',
    ProductAnalytics = ProductKey.PRODUCT_ANALYTICS,
    SessionReplay = ProductKey.SESSION_REPLAY,
    FeatureFlags = ProductKey.FEATURE_FLAGS,
    Experiments = ProductKey.EXPERIMENTS,
    DataWarehouse = ProductKey.DATA_WAREHOUSE,
    Surveys = ProductKey.SURVEYS,
}

function IngestFirstEventContent(): JSX.Element {
    return <>Ingest your first event to get started with PostHog</>
}

function InviteTeamMemberContent(): JSX.Element {
    return <>Everyone in your organization can benefit from PostHog</>
}

function CreateFirstInsightContent(): JSX.Element {
    return <>Make sense of your data by creating an insight</>
}

function CreateFirstDashboardContent(): JSX.Element {
    return <>Collect your insights in a dashboard</>
}

function SetupSessionRecordingsContent(): JSX.Element {
    return <>See how your users are using your product</>
}

function TrackCustomEventsContent(): JSX.Element {
    return <>Add custom ddd events to get more insights into your product</>
}

function SetUpReverseProxyContent(): JSX.Element {
    return <>Proxy your domain traffic to avoid tracking blockers</>
}

/** 3b) "ActivationTaskType" now has "title" and "content" (ReactNode),
 * plus metadata for completion/skipping, etc.
 */
export type ActivationTaskType = {
    id: ActivationTask
    section: ActivationSection
    title: string
    content: React.ReactNode
    completed: boolean
    canSkip: boolean
    skipped: boolean
    url?: string
}

// make sure to change this prefix in case the schema of cached values is changed
// otherwise the code will try to run with cached deprecated values
const CACHE_PREFIX = 'v1'

export const activationLogic = kea<activationLogicType>([
    path(['lib', 'components', 'ActivationSidebar', 'activationLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            membersLogic,
            ['memberCount'],
            inviteLogic,
            ['invites'],
            savedInsightsLogic,
            ['insights'],
            dashboardsModel,
            ['rawDashboards'],
            reverseProxyCheckerLogic,
            ['hasReverseProxy'],
            featureFlagsLogic,
            ['featureFlags'],
            experimentsLogic,
            ['experiments'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
            surveysLogic,
            ['surveys'],
        ],
        actions: [
            inviteLogic,
            ['showInviteModal', 'loadInvitesSuccess', 'loadInvitesFailure', 'loadInvites'],
            sidePanelStateLogic,
            ['openSidePanel'],
            savedInsightsLogic,
            ['loadInsights', 'loadInsightsSuccess', 'loadInsightsFailure'],
            dashboardsModel,
            ['loadDashboardsSuccess', 'loadDashboardsFailure'],
            featureFlagsLogic,
            ['loadFeatureFlags', 'loadFeatureFlagsSuccess', 'loadFeatureFlagsFailure'],
            experimentsLogic,
            ['loadExperiments', 'loadExperimentsSuccess', 'loadExperimentsFailure'],
            dataWarehouseSettingsLogic,
            ['loadSources', 'loadSourcesSuccess', 'loadSourcesFailure'],
            sidePanelSettingsLogic,
            ['openSettingsPanel'],
        ],
    })),
    actions({
        loadCustomEvents: true,
        runTask: (id: string) => ({ id }),
        skipTask: (id: string) => ({ id }),
        addSkippedTask: (teamId: TeamBasicType['id'], taskId: string) => ({ teamId, taskId }),
    }),
    reducers(() => ({
        skippedTasks: [
            {} as Record<string, string[]>,
            { persist: true, prefix: CACHE_PREFIX },
            {
                addSkippedTask: (state, { teamId, taskId }) => {
                    return { ...state, [teamId]: [...(state[teamId] ?? []), taskId] }
                },
            },
        ],
        areInvitesLoaded: [
            false,
            {
                loadInvitesSuccess: () => true,
                loadInvitesFailure: () => false,
            },
        ],
        areDashboardsLoaded: [
            false,
            {
                loadDashboardsSuccess: () => true,
                loadDashboardsFailure: () => false,
            },
        ],
        areCustomEventsLoaded: [
            false,
            {
                loadCustomEventsSuccess: () => true,
                loadCustomEventsFailure: () => false,
            },
        ],
        areInsightsLoaded: [
            false,
            {
                loadInsightsSuccess: () => true,
                loadInsightsFailure: () => false,
            },
        ],
        areFeatureFlagsLoaded: [
            false,
            {
                loadFeatureFlagsSuccess: () => true,
                loadFeatureFlagsFailure: () => false,
            },
        ],
        areExperimentsLoaded: [
            false,
            {
                loadExperimentsSuccess: () => true,
                loadExperimentsFailure: () => false,
            },
        ],
        areSourcesLoaded: [
            false,
            {
                loadSourcesSuccess: () => true,
                loadSourcesFailure: () => false,
            },
        ],
    })),
    loaders(({ cache }) => ({
        customEventsCount: [
            0,
            {
                loadCustomEvents: async (_, breakpoint) => {
                    await breakpoint(200)
                    const url = api.eventDefinitions.determineListEndpoint({
                        event_type: EventDefinitionType.EventCustom,
                    })
                    if (url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }
                    cache.eventsStartTime = performance.now()
                    const response = await api.get(url)
                    breakpoint()
                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [url]: response.count,
                    }
                    return cache.apiCache[url]
                },
            },
        ],
    })),
    selectors({
        isReady: [
            (s) => [
                s.currentTeam,
                s.memberCount,
                s.areInvitesLoaded,
                s.areDashboardsLoaded,
                s.areCustomEventsLoaded,
                s.areInsightsLoaded,
                s.areFeatureFlagsLoaded,
                s.areExperimentsLoaded,
                s.areSourcesLoaded,
            ],
            (
                currentTeam,
                memberCount,
                areInvitesLoaded,
                areDashboardsLoaded,
                areCustomEventsLoaded,
                areInsightsLoaded,
                areFeatureFlagsLoaded,
                areExperimentsLoaded,
                areSourcesLoaded
            ): boolean => {
                return (
                    !!currentTeam &&
                    areCustomEventsLoaded &&
                    areInsightsLoaded &&
                    !!memberCount &&
                    areInvitesLoaded &&
                    areDashboardsLoaded &&
                    areFeatureFlagsLoaded &&
                    areExperimentsLoaded &&
                    areSourcesLoaded
                )
            },
        ],
        currentTeamSkippedTasks: [
            (s) => [s.skippedTasks, s.currentTeam],
            (skippedTasks, currentTeam) => skippedTasks[currentTeam?.id ?? ''] ?? [],
        ],
        hasCreatedDashboard: [
            (s) => [s.rawDashboards],
            (dashboards) => Object.values(dashboards).find((dashboard) => dashboard.created_by !== null) !== undefined,
        ],
        hasSources: [(s) => [s.dataWarehouseSources], (sources) => (sources?.results ?? []).length > 0],
        hasCreatedIndependentFeatureFlag: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsResult) =>
                (featureFlags?.results ?? []).some(
                    (featureFlag) =>
                        (!featureFlag.experiment_set || featureFlag.experiment_set.length === 0) &&
                        (!featureFlag.surveys || featureFlag.surveys.length === 0)
                ),
        ],
        hasLaunchedExperiment: [
            (s) => [s.experiments],
            (experiments: Experiment[]) => (experiments ?? []).filter((e) => e.start_date).length > 0,
        ],
        hasInsights: [(s) => [s.insights], (insights) => (insights?.results ?? []).length > 0],
        hasSurveys: [(s) => [s.surveys], (surveys) => (surveys ?? []).length > 0],
        hasInvitesOrMembers: [
            (s) => [s.memberCount, s.invites],
            (memberCount, invites) => memberCount > 1 || invites.length > 0,
        ],
        hasCustomEvents: [(s) => [s.customEventsCount], (customEventsCount) => customEventsCount > 0],
        hasCompletedFirstOnboarding: [
            (s) => [s.currentTeam],
            (currentTeam) =>
                Object.keys(currentTeam?.has_completed_onboarding_for || {}).some(
                    (key) => currentTeam?.has_completed_onboarding_for?.[key] === true
                ),
        ],
        tasks: [
            (s) => [
                s.currentTeam,
                s.currentTeamSkippedTasks,
                s.hasReverseProxy,
                s.hasSources,
                s.hasCreatedIndependentFeatureFlag,
                s.hasLaunchedExperiment,
                s.hasCreatedDashboard,
                s.hasInsights,
                s.hasSurveys,
                s.hasInvitesOrMembers,
                s.hasCustomEvents,
            ],
            (
                currentTeam,
                currentTeamSkippedTasks,
                hasReverseProxy,
                hasSources,
                hasCreatedIndependentFeatureFlag,
                hasLaunchedExperiment,
                hasCreatedDashboard,
                hasInsights,
                hasSurveys,
                hasInvitesOrMembers,
                hasCustomEvents
            ) => {
                const tasks = [
                    {
                        id: ActivationTask.IngestFirstEvent,
                        title: 'Ingest your first event',
                        content: <IngestFirstEventContent />,
                        canSkip: false,
                        skipped: false,
                        section: ActivationSection.QuickStart,
                        completed: currentTeam?.ingested_event ?? false,
                    },
                    {
                        id: ActivationTask.InviteTeamMember,
                        title: 'Invite a team member',
                        content: <InviteTeamMemberContent />,
                        completed: hasInvitesOrMembers,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.QuickStart,
                    },
                    {
                        id: ActivationTask.CreateFirstInsight,
                        title: 'Create your first insight',
                        content: <CreateFirstInsightContent />,
                        completed: hasInsights,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.ProductAnalytics,
                    },
                    {
                        id: ActivationTask.CreateFirstDashboard,
                        title: 'Create your first dashboard',
                        content: <CreateFirstDashboardContent />,
                        completed: hasCreatedDashboard,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.ProductAnalytics,
                    },

                    {
                        id: ActivationTask.TrackCustomEvents,
                        title: 'Track custom events',
                        completed: hasCustomEvents,
                        content: <TrackCustomEventsContent />,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.ProductAnalytics,
                        url: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                    },
                    {
                        id: ActivationTask.SetUpReverseProxy,
                        title: 'Set up a reverse proxy',
                        content: <SetUpReverseProxyContent />,
                        completed: hasReverseProxy || false,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.QuickStart,
                        url: 'https://posthog.com/docs/advanced/proxy',
                    },
                    // Sesion Replay
                    {
                        id: ActivationTask.SetupSessionRecordings,
                        title: 'Set up session recordings',
                        completed: currentTeam?.session_recording_opt_in ?? false,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: false,
                        skipped: false,
                        section: ActivationSection.SessionReplay,
                    },
                    {
                        id: ActivationTask.WatchSessionRecording,
                        title: 'Watch a session recording',
                        completed: currentTeam?.session_recording_opt_in ?? false,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: false,
                        skipped: false,
                        section: ActivationSection.SessionReplay,
                    },
                    // Feature Flags
                    {
                        id: ActivationTask.CreateFeatureFlag,
                        section: ActivationSection.FeatureFlags,
                        title: 'Create a feature flag',
                        completed: hasCreatedIndependentFeatureFlag,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: true,
                        skipped: false,
                    },
                    // Experiments
                    {
                        id: ActivationTask.LaunchExperiment,
                        section: ActivationSection.Experiments,
                        title: 'Launch an experiment',
                        completed: hasLaunchedExperiment,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: true,
                        skipped: false,
                    },
                    // Data Pipelines
                    {
                        id: ActivationTask.ConnectSource,
                        title: 'Connect external data source',
                        completed: hasSources,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.DataWarehouse,
                    },
                    {
                        id: ActivationTask.ConnectDestination,
                        title: 'Send data to a destination',
                        completed: hasSources,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.DataWarehouse,
                    },
                    // Surveys
                    {
                        id: ActivationTask.LaunchSurvey,
                        title: 'Launch a survey',
                        completed: hasSurveys,
                        content: <SetupSessionRecordingsContent />,
                        canSkip: true,
                        skipped: false,
                        section: ActivationSection.Surveys,
                    },
                ]

                return tasks
            },
        ],
        /** 5) Filter tasks for display. */
        activeTasks: [(s) => [s.tasks], (tasks) => tasks.filter((t) => !t.completed && !t.skipped)],
        completedTasks: [(s) => [s.tasks], (tasks) => tasks.filter((t) => t.completed || t.skipped)],
        completionPercent: [
            (s) => [s.completedTasks, s.activeTasks],
            (completedTasks, activeTasks) => {
                const totalDone = completedTasks.length
                const totalAll = completedTasks.length + activeTasks.length
                const percent = totalAll > 0 ? Math.round((totalDone / totalAll) * 100) : 0
                // Return at least 5 to ensure a visible fraction on the progress circle
                return percent >= 5 ? percent : 5
            },
        ],
        hasCompletedAllTasks: [(s) => [s.activeTasks], (activeTasks) => activeTasks.length === 0],
    }),
    listeners(({ actions, values }) => ({
        runTask: async ({ id }) => {
            switch (id) {
                case ActivationTask.IngestFirstEvent:
                    router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS))
                    break
                case ActivationTask.InviteTeamMember:
                    actions.showInviteModal()
                    break
                case ActivationTask.CreateFirstInsight:
                    router.actions.push(urls.insightNew())
                    break
                case ActivationTask.CreateFirstDashboard:
                    router.actions.push(urls.dashboards())
                    break
                case ActivationTask.SetupSessionRecordings:
                    actions.openSettingsPanel({ sectionId: 'project-replay' })
                    router.actions.push(urls.replay(ReplayTabs.Home))
                    break
                case ActivationTask.WatchSessionRecording:
                    router.actions.push(urls.replay(ReplayTabs.Playlists))
                    break
                case ActivationTask.TrackCustomEvents:
                    router.actions.push(urls.eventDefinitions())
                    break
                case ActivationTask.CreateFeatureFlag:
                    router.actions.push(urls.featureFlag('new'))
                    break
                case ActivationTask.LaunchExperiment:
                    router.actions.push(urls.experiment('new'))
                    break
                case ActivationTask.ConnectSource:
                    router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                    break
                case ActivationTask.ConnectDestination:
                    router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination))
                    break
                case ActivationTask.LaunchSurvey:
                    router.actions.push(urls.surveyTemplates())
                    break
                default:
                    // For tasks with just a URL or no direct route
                    break
            }
        },
        skipTask: ({ id }) => {
            posthog.capture('activation sidebar task skipped', {
                task: id,
            })
            if (values.currentTeam?.id) {
                actions.addSkippedTask(values.currentTeam.id, id)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCustomEvents()
            actions.loadInsights()
            actions.loadInvites()
        },
    })),
    permanentlyMount(),
])

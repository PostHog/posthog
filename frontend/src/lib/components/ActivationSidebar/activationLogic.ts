import { kea, path, actions, selectors, connect, reducers, listeners, events } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { EventDefinitionType, ProductKey, TeamBasicType } from '~/types'
import type { activationLogicType } from './activationLogicType'
import { urls } from 'scenes/urls'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

export enum ActivationTasks {
    IngestFirstEvent = 'ingest_first_event',
    InviteTeamMember = 'invite_team_member',
    CreateFirstInsight = 'create_first_insight',
    CreateFirstDashboard = 'create_first_dashboard',
    SetupSessionRecordings = 'setup_session_recordings',
    TrackCustomEvents = 'track_custom_events',
    InstallFirstApp = 'install_first_app',
}

export type ActivationTaskType = {
    id: ActivationTasks
    name: string
    description: string
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
            ['members'],
            inviteLogic,
            ['invites'],
            pluginsLogic,
            ['installedPlugins'],
            savedInsightsLogic,
            ['insights'],
            dashboardsModel,
            ['rawDashboards'],
        ],
        actions: [
            membersLogic,
            ['loadMembersSuccess', 'loadMembersFailure'],
            inviteLogic,
            ['showInviteModal', 'loadInvitesSuccess', 'loadInvitesFailure'],
            pluginsLogic,
            ['loadPluginsSuccess', 'loadPluginsFailure'],
            navigationLogic,
            ['toggleActivationSideBar', 'showActivationSideBar', 'hideActivationSideBar'],
            eventUsageLogic,
            ['reportActivationSideBarShown'],
            savedInsightsLogic,
            ['loadInsights', 'loadInsightsSuccess', 'loadInsightsFailure'],
            dashboardsModel,
            ['loadDashboardsSuccess', 'loadDashboardsFailure'],
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
        areMembersLoaded: [
            false,
            {
                loadMembersSuccess: () => true,
                loadMembersFailure: () => false,
            },
        ],
        areInvitesLoaded: [
            false,
            {
                loadInvitesSuccess: () => true,
                loadInvitesFailure: () => false,
            },
        ],
        arePluginsLoaded: [
            false,
            {
                loadPluginsSuccess: () => true,
                loadPluginsFailure: () => false,
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
                s.areMembersLoaded,
                s.areInvitesLoaded,
                s.areDashboardsLoaded,
                s.arePluginsLoaded,
                s.areCustomEventsLoaded,
                s.areInsightsLoaded,
            ],
            (
                currentTeam,
                areMembersLoaded,
                areInvitesLoaded,
                areDashboardsLoaded,
                arePluginsLoaded,
                areCustomEventsLoaded,
                areInsightsLoaded
            ) => {
                return (
                    !!currentTeam &&
                    areCustomEventsLoaded &&
                    areInsightsLoaded &&
                    areMembersLoaded &&
                    areInvitesLoaded &&
                    areDashboardsLoaded &&
                    arePluginsLoaded
                )
            },
        ],
        currentTeamSkippedTasks: [
            (s) => [s.skippedTasks, s.currentTeam],
            (skippedTasks, currentTeam) => skippedTasks[currentTeam?.id ?? ''] ?? [],
        ],
        tasks: [
            (s) => [
                s.currentTeam,
                s.members,
                s.invites,
                s.insights,
                s.rawDashboards,
                s.customEventsCount,
                s.installedPlugins,
                s.currentTeamSkippedTasks,
            ],
            (
                currentTeam,
                members,
                invites,
                insights,
                dashboards,
                customEventsCount,
                installedPlugins,
                skippedTasks
            ) => {
                const tasks: ActivationTaskType[] = []
                for (const task of Object.values(ActivationTasks)) {
                    switch (task) {
                        case ActivationTasks.IngestFirstEvent:
                            tasks.push({
                                id: ActivationTasks.IngestFirstEvent,
                                name: 'Ingest your first event',
                                description: 'Ingest your first event to get started with PostHog',
                                completed: currentTeam?.ingested_event ?? false,
                                canSkip: false,
                                skipped: false,
                            })
                            break
                        case ActivationTasks.InviteTeamMember:
                            tasks.push({
                                id: ActivationTasks.InviteTeamMember,
                                name: 'Invite a team member',
                                description: 'Everyone in your organization can benefit from PostHog',
                                completed: members.length > 1 || invites.length > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.InviteTeamMember),
                            })
                            break
                        case ActivationTasks.CreateFirstInsight:
                            tasks.push({
                                id: ActivationTasks.CreateFirstInsight,
                                name: 'Create your first insight',
                                description: 'Make sense of your data by creating an insight',
                                completed:
                                    insights.results.find((insight) => insight.created_by !== null) !== undefined,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.CreateFirstInsight),
                            })
                            break
                        case ActivationTasks.CreateFirstDashboard:
                            tasks.push({
                                id: ActivationTasks.CreateFirstDashboard,
                                name: 'Create your first dashboard',
                                description: 'Collect your insights in a dashboard',
                                completed:
                                    Object.values(dashboards).find((dashboard) => dashboard.created_by !== null) !==
                                    undefined,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.CreateFirstDashboard),
                            })
                            break
                        case ActivationTasks.SetupSessionRecordings:
                            tasks.push({
                                id: ActivationTasks.SetupSessionRecordings,
                                name: 'Set up session recordings',
                                description: 'See how your users are using your product',
                                completed: currentTeam?.session_recording_opt_in ?? false,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.SetupSessionRecordings),
                            })
                            break
                        case ActivationTasks.TrackCustomEvents:
                            tasks.push({
                                id: ActivationTasks.TrackCustomEvents,
                                name: 'Track custom events',
                                description: 'Track custom events to get more insights into your product',
                                completed: customEventsCount > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.TrackCustomEvents),
                                url: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                            })
                            break
                        case ActivationTasks.InstallFirstApp:
                            tasks.push({
                                id: ActivationTasks.InstallFirstApp,
                                name: 'Install your first app',
                                description: `Extend PostHog's core functionality with apps`,
                                completed: installedPlugins.length > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ActivationTasks.InstallFirstApp),
                            })
                            break
                        default:
                            break
                    }
                }
                return tasks
            },
        ],
        activeTasks: [
            (s) => [s.tasks],
            (tasks) => {
                return tasks.filter((task) => !task.completed && !task.skipped)
            },
        ],
        completedTasks: [
            (s) => [s.tasks],
            (tasks) => {
                return tasks.filter((task) => task.completed || task.skipped)
            },
        ],
        completionPercent: [
            (s) => [s.completedTasks, s.activeTasks],
            (completedTasks, activeTasks) => {
                const percent = Math.round((completedTasks.length / (completedTasks.length + activeTasks.length)) * 100)
                // we return 5 so that the progress bar is always visible
                return percent > 0 ? percent : 5
            },
        ],
        hasCompletedAllTasks: [
            (s) => [s.activeTasks],
            (activeTasks) => {
                return activeTasks.length === 0
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        runTask: async ({ id }) => {
            switch (id) {
                case ActivationTasks.IngestFirstEvent:
                    router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS))
                    break
                case ActivationTasks.InviteTeamMember:
                    actions.showInviteModal()
                    break
                case ActivationTasks.CreateFirstInsight:
                    router.actions.push(urls.insightNew())
                    break
                case ActivationTasks.CreateFirstDashboard:
                    router.actions.push(urls.dashboards())
                    break
                case ActivationTasks.SetupSessionRecordings:
                    router.actions.push(urls.replay())
                    break
                case ActivationTasks.InstallFirstApp:
                    router.actions.push(urls.projectApps())
                    break
                default:
                    break
            }
        },
        skipTask: ({ id }) => {
            if (values.currentTeam?.id) {
                actions.addSkippedTask(values.currentTeam.id, id)
            }
        },
        showActivationSideBar: async () => {
            actions.reportActivationSideBarShown(
                values.activeTasks.length,
                values.completedTasks.length,
                values.completionPercent
            )
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCustomEvents()
            actions.loadInsights()
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, params) => {
            if (params?.onboarding_completed && !values.hasCompletedAllTasks) {
                actions.toggleActivationSideBar()
            } else {
                actions.hideActivationSideBar()
            }
        },
    })),
    permanentlyMount(),
])

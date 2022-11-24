import { kea, path, actions, selectors, connect, reducers, listeners, events } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { EventDefinitionType } from '~/types'

import type { activationLogicType } from './ActivationLogicType'

export enum ACTIVATION_TASKS {
    INGEST_FIRST_EVENT = 'ingest_first_event',
    INVITE_TEAM_MEMBER = 'invite_team_member',
    SETUP_SESSION_RECORDINGS = 'setup_session_recordings',
    TRACK_CUSTOM_EVENTS = 'track_custom_events',
    INSTALL_FIRST_APP = 'install_first_app',
}

export type Task = {
    id: ACTIVATION_TASKS
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
    connect({
        values: [
            teamLogic,
            ['currentTeam'],
            membersLogic,
            ['members'],
            inviteLogic,
            ['invites'],
            pluginsLogic,
            ['installedPlugins'],
        ],
        actions: [
            inviteLogic,
            ['showInviteModal'],
            navigationLogic,
            ['toggleActivationSideBar', 'hideActivationSideBar'],
        ],
    }),
    actions({
        loadCustomEvents: true,
        runTask: (id: string) => ({ id }),
        skipTask: (id: string) => ({ id }),
        setShowSessionRecordingConfig: (value: boolean) => ({ value }),
    }),
    reducers({
        skippedTasks: [
            [] as string[],
            { persist: true, prefix: CACHE_PREFIX },
            {
                skipTask: (state, { id }) => [...state, id],
            },
        ],
        showSessionRecordingConfig: [
            false,
            {
                setShowSessionRecordingConfig: (_, { value }) => value,
            },
        ],
        isReady: [
            false,
            {
                loadCustomEventsSuccess: () => true,
                loadCustomEventsFailure: () => true,
            },
        ],
    }),
    loaders(({ cache }) => ({
        customEventsCount: [
            0,
            {
                loadCustomEvents: async ({}, breakpoint) => {
                    breakpoint(200)
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
        tasks: [
            (s) => [s.currentTeam, s.members, s.invites, s.customEventsCount, s.installedPlugins, s.skippedTasks],
            (currentTeam, members, invites, customEventsCount, installedPlugins, skippedTasks) => {
                const tasks: Task[] = []
                for (const task of Object.values(ACTIVATION_TASKS)) {
                    switch (task) {
                        case ACTIVATION_TASKS.INGEST_FIRST_EVENT:
                            tasks.push({
                                id: ACTIVATION_TASKS.INGEST_FIRST_EVENT,
                                name: 'Ingest your first event',
                                description: 'Ingest your first event to get started with PostHog',
                                completed: currentTeam?.ingested_event ?? false,
                                canSkip: false,
                                skipped: false,
                            })
                            break
                        case ACTIVATION_TASKS.INVITE_TEAM_MEMBER:
                            tasks.push({
                                id: ACTIVATION_TASKS.INVITE_TEAM_MEMBER,
                                name: 'Invite a team member',
                                description: 'Every person in your company can benefit from PostHog',
                                completed: members.length > 1 || invites.length > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ACTIVATION_TASKS.INVITE_TEAM_MEMBER),
                            })
                            break
                        case ACTIVATION_TASKS.SETUP_SESSION_RECORDINGS:
                            tasks.push({
                                id: ACTIVATION_TASKS.SETUP_SESSION_RECORDINGS,
                                name: 'Setup session recordings',
                                description: 'See how your users are using your product',
                                completed: currentTeam?.session_recording_opt_in ?? false,
                                canSkip: true,
                                skipped: skippedTasks.includes(ACTIVATION_TASKS.SETUP_SESSION_RECORDINGS),
                            })
                            break
                        case ACTIVATION_TASKS.TRACK_CUSTOM_EVENTS:
                            tasks.push({
                                id: ACTIVATION_TASKS.TRACK_CUSTOM_EVENTS,
                                name: 'Track custom events',
                                description: 'Track custom events to get more insights into your product',
                                completed: customEventsCount > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ACTIVATION_TASKS.TRACK_CUSTOM_EVENTS),
                                url: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                            })
                            break
                        case ACTIVATION_TASKS.INSTALL_FIRST_APP:
                            tasks.push({
                                id: ACTIVATION_TASKS.INSTALL_FIRST_APP,
                                name: 'Install your first app',
                                description: `Extend PostHog's core functionality with apps`,
                                completed: installedPlugins.length > 0,
                                canSkip: true,
                                skipped: skippedTasks.includes(ACTIVATION_TASKS.INSTALL_FIRST_APP),
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
    listeners(({ actions }) => ({
        runTask: async ({ id }) => {
            switch (id) {
                case ACTIVATION_TASKS.INGEST_FIRST_EVENT:
                    window.location.href = '/ingestion'
                    break
                case ACTIVATION_TASKS.INVITE_TEAM_MEMBER:
                    actions.showInviteModal()
                    break
                case ACTIVATION_TASKS.SETUP_SESSION_RECORDINGS:
                    actions.setShowSessionRecordingConfig(true)
                    break
                case ACTIVATION_TASKS.INSTALL_FIRST_APP:
                    window.location.href = '/project/apps'
                    break
                default:
                    break
            }
        },
        toggleActivationSideBar: async () => {
            actions.setShowSessionRecordingConfig(false)
        },
        [router.actionTypes.locationChanged]: async () => {
            actions.hideActivationSideBar()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCustomEvents()
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, params) => {
            if (params?.onboarding_completed && !values.hasCompletedAllTasks) {
                actions.toggleActivationSideBar()
            }
        },
    })),
])

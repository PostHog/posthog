import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import {
    IconDatabase,
    IconFeatures,
    IconGraph,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'

import api from 'lib/api'
import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { availableOnboardingProducts } from 'scenes/onboarding/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    ActivationTaskStatus,
    EventDefinitionType,
    OnboardingStepKey,
    ProductKey,
    ReplayTabs,
    TeamBasicType,
    type TeamPublicType,
    type TeamType,
} from '~/types'

import { sidePanelSettingsLogic } from '../sidePanelSettingsLogic'
import type { activationLogicType } from './activationLogicType'

export type ActivationTaskDefinition = {
    id: ActivationTask
    section: ActivationSection
    title: string
    canSkip: boolean
    dependsOn?: {
        task: ActivationTask
        reason: string
    }[]
    url?: string
    buttonText?: string
}

export type ActivationTaskType = Omit<ActivationTaskDefinition, 'dependsOn'> & {
    completed: boolean
    skipped: boolean
    lockedReason?: string
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
            sidePanelStateLogic,
            ['modalMode'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            teamLogic,
            ['loadCurrentTeam', 'updateCurrentTeam'],
            inviteLogic,
            ['showInviteModal'],
            sidePanelSettingsLogic,
            ['openSettingsPanel'],
            sidePanelStateLogic,
            ['openSidePanel', 'closeSidePanel'],
            teamLogic,
            ['addProductIntent'],
            reverseProxyCheckerLogic,
            ['loadHasReverseProxy'],
        ],
    })),
    actions({
        runTask: (id: ActivationTask) => ({ id }),
        markTaskAsCompleted: (id: ActivationTask) => ({ id }),
        markTaskAsSkipped: (id: ActivationTask) => ({ id }),
        toggleShowHiddenSections: () => ({}),
        addIntentForSection: (section: ActivationSection) => ({ section }),
        toggleSectionOpen: (section: ActivationSection) => ({ section }),
        setOpenSections: (teamId: TeamBasicType['id'], sections: ActivationSection[]) => ({ teamId, sections }),
        onTeamLoad: (team: TeamType | TeamPublicType | null) => ({ team }),
        setExpandedTaskId: (taskId: ActivationTask | null) => ({ taskId }),
        setTaskContentHeight: (taskId: ActivationTask, height: number) => ({ taskId, height }),
    }),
    reducers(() => ({
        openSections: [
            {} as Record<string, ActivationSection[]>,
            { persist: true, prefix: CACHE_PREFIX },
            {
                setOpenSections: (state, { teamId, sections }) => {
                    return {
                        ...state,
                        [teamId]: sections,
                    }
                },
            },
        ],
        showHiddenSections: [
            false,
            {
                toggleShowHiddenSections: (state) => !state,
            },
        ],
        expandedTaskId: [
            null as ActivationTask | null,
            {
                setExpandedTaskId: (_state, { taskId }) => taskId,
            },
        ],
        taskContentHeights: [
            {} as Record<ActivationTask, number>,
            {
                setTaskContentHeight: (state, { taskId, height }) => ({
                    ...state,
                    [taskId]: height,
                }),
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
                        ...cache.apiCache,
                        [url]: response.count,
                    }
                    return cache.apiCache[url]
                },
            },
        ],
    })),
    selectors({
        savedOnboardingTasks: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.onboarding_tasks ?? ({} as Record<ActivationTask, ActivationTaskStatus>),
        ],
        isReady: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => {
                return !!currentTeam
            },
        ],
        currentTeamOpenSections: [
            (s) => [s.openSections, s.currentTeam],
            (openSections, currentTeam) => (currentTeam?.id ? (openSections[currentTeam?.id] ?? []) : []),
        ],
        hasCompletedFirstOnboarding: [
            (s) => [s.currentTeam],
            (currentTeam) =>
                Object.keys(currentTeam?.has_completed_onboarding_for || {}).some(
                    (key) => currentTeam?.has_completed_onboarding_for?.[key] === true
                ),
        ],
        hasHiddenSections: [(s) => [s.sections], (sections) => sections.filter((s) => !s.visible).length > 0],
        showSaveInsightTask: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.SAVE_INSIGHT_TASK] === 'test',
        ],
        tasks: [
            (s) => [s.savedOnboardingTasks, s.showSaveInsightTask],
            (savedOnboardingTasks, showSaveInsightTask) => {
                const tasks: ActivationTaskType[] = ACTIVATION_TASKS.map((task) => {
                    const title =
                        task.id === ActivationTask.CreateFirstInsight && showSaveInsightTask
                            ? 'Save an insight'
                            : task.title
                    return {
                        ...task,
                        skipped: task.canSkip && savedOnboardingTasks[task.id] === ActivationTaskStatus.SKIPPED,
                        completed: savedOnboardingTasks[task.id] === ActivationTaskStatus.COMPLETED,
                        lockedReason: task.dependsOn?.find(
                            (d) => savedOnboardingTasks[d.task] !== ActivationTaskStatus.COMPLETED
                        )?.reason,
                        title,
                    }
                })

                return tasks
            },
        ],
        visibleTasks: [
            (s) => [s.tasks, s.sections],
            (tasks, sections): ActivationTaskType[] => {
                return tasks.filter((task) => sections.find((s) => s.key === task.section)?.visible)
            },
        ],
        activeTasks: [
            (s) => [s.visibleTasks],
            (visibleTasks) => visibleTasks.filter((task) => !task.completed && !task.skipped),
        ],
        completionPercent: [
            (s) => [s.visibleTasks],
            (visibleTasks) => {
                const doneTasks = visibleTasks.filter((task) => task.completed || task.skipped).length
                const percent = visibleTasks.length > 0 ? Math.round((doneTasks / visibleTasks.length) * 100) : 0
                // Return at least 5 to ensure a visible fraction on the progress circle
                return percent >= 5 ? percent : 5
            },
        ],
        shouldShowActivationTab: [
            (s) => [s.isReady, s.hasCompletedFirstOnboarding, s.hasCompletedAllVisibleTasks],
            (isReady, hasCompletedFirstOnboarding, hasCompletedAllVisibleTasks) =>
                isReady && hasCompletedFirstOnboarding && !hasCompletedAllVisibleTasks,
        ],
        hasCompletedAllVisibleTasks: [
            (s) => [s.visibleTasks],
            (visibleTasks) => visibleTasks.every((task) => task.completed),
        ],
        productsWithIntent: [
            (s) => [s.currentTeam],
            (currentTeam: TeamType | TeamPublicType | null) => {
                return currentTeam?.product_intents?.map((intent) => intent.product_type as ProductKey)
            },
        ],
        sections: [
            (s) => [s.productsWithIntent, s.currentTeamOpenSections, s.isReady],
            (productsWithIntent, currentTeamOpenSections, isReady) => {
                if (!isReady) {
                    return []
                }

                return Object.entries(ACTIVATION_SECTIONS).map(([sectionKey, section]) => {
                    return {
                        ...section,
                        key: sectionKey as ActivationSection,
                        open: currentTeamOpenSections.includes(sectionKey as ActivationSection),
                        visible:
                            sectionKey === ActivationSection.QuickStart ||
                            Boolean(productsWithIntent?.includes(sectionKey as ProductKey)),
                    }
                })
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        runTask: async ({ id }) => {
            if (values.modalMode) {
                actions.closeSidePanel()
            }

            switch (id) {
                // Quick Start
                case ActivationTask.IngestFirstEvent:
                    router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INSTALL))
                    break
                case ActivationTask.InviteTeamMember:
                    actions.showInviteModal()
                    break

                // Product Analytics
                case ActivationTask.CreateFirstInsight:
                    router.actions.push(urls.insightNew())
                    break
                case ActivationTask.CreateFirstDashboard:
                    router.actions.push(urls.dashboards() + '#newDashboard=modal')
                    break

                // Web Analytics
                case ActivationTask.AddAuthorizedDomain:
                    router.actions.push(urls.settings('environment', 'web-analytics-authorized-urls'))
                    break
                case ActivationTask.SetUpWebVitals:
                    router.actions.push(urls.settings('environment-autocapture', 'web-vitals-autocapture'))
                    break

                // Session Replay
                case ActivationTask.SetupSessionRecordings:
                    actions.openSettingsPanel({ sectionId: 'project-replay' })
                    router.actions.push(urls.replay(ReplayTabs.Home))
                    break
                case ActivationTask.WatchSessionRecording:
                    router.actions.push(urls.replay(ReplayTabs.Home))
                    break
                case ActivationTask.TrackCustomEvents:
                    router.actions.push(urls.eventDefinitions())
                    break

                // Feature Flags
                case ActivationTask.CreateFeatureFlag:
                    router.actions.push(urls.featureFlags())
                    break
                case ActivationTask.UpdateFeatureFlagReleaseConditions:
                    router.actions.push(urls.featureFlags())
                    break

                // Experiments
                case ActivationTask.LaunchExperiment:
                    router.actions.push(urls.experiments())
                    break

                // Data Warehouse
                case ActivationTask.ConnectSource:
                    router.actions.push(urls.dataWarehouseSourceNew())
                    break

                // Surveys
                case ActivationTask.LaunchSurvey:
                    router.actions.push(urls.surveyTemplates())
                    break
                case ActivationTask.CollectSurveyResponses:
                    router.actions.push(urls.surveys())
                    break
                default:
                    // For tasks with just a URL or no direct route
                    break
            }
        },
        markTaskAsSkipped: ({ id }) => {
            const skipped = values.currentTeam?.onboarding_tasks?.[id] === ActivationTaskStatus.SKIPPED

            if (skipped) {
                return
            }

            posthog.capture('activation sidebar task skipped', {
                task: id,
            })

            actions.updateCurrentTeam({
                onboarding_tasks: {
                    ...values.currentTeam?.onboarding_tasks,
                    [id]: ActivationTaskStatus.SKIPPED,
                },
            })
        },
        markTaskAsCompleted: ({ id }) => {
            const completed = values.currentTeam?.onboarding_tasks?.[id] === ActivationTaskStatus.COMPLETED

            if (completed) {
                return
            }

            posthog.capture('activation sidebar task completed', {
                task: id,
            })

            actions.updateCurrentTeam({
                onboarding_tasks: {
                    ...values.currentTeam?.onboarding_tasks,
                    [id]: ActivationTaskStatus.COMPLETED,
                },
            })
        },
        addIntentForSection: ({ section }) => {
            const productKey = Object.values(ProductKey).find((key) => String(key) === String(section))

            if (productKey) {
                actions.addProductIntent({
                    product_type: productKey,
                    intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
                })
            }
        },
        toggleSectionOpen: ({ section }) => {
            if (values.currentTeam?.id) {
                const openSections = values.currentTeamOpenSections.includes(section)
                    ? values.currentTeamOpenSections.filter((s) => s !== section)
                    : [...values.currentTeamOpenSections, section]
                actions.setOpenSections(values.currentTeam.id, openSections)
            }
        },
        openSidePanel: () => {
            if (values.currentTeamOpenSections.length === 0 && values.currentTeam?.id) {
                const sectionsToOpen = values.sections
                    .filter(
                        (s) =>
                            s.key === ActivationSection.QuickStart ||
                            values.productsWithIntent?.includes(s.key as unknown as ProductKey)
                    )
                    .map((s) => s.key)

                actions.setOpenSections(values.currentTeam.id, sectionsToOpen)
            }

            if (!values.currentTeam?.onboarding_tasks?.[ActivationTask.SetUpReverseProxy]) {
                actions.loadHasReverseProxy()
            }

            if (!values.currentTeam?.onboarding_tasks?.[ActivationTask.TrackCustomEvents]) {
                actions.loadCustomEvents({})
            }
        },
        loadCustomEventsSuccess: () => {
            if (values.customEventsCount > 0) {
                actions.markTaskAsCompleted(ActivationTask.TrackCustomEvents)
            }
        },
        onTeamLoad: ({ team }) => {
            const teamPropertiesToCheck: { property: keyof TeamType; task: ActivationTask }[] = [
                {
                    property: 'session_recording_opt_in',
                    task: ActivationTask.SetupSessionRecordings,
                },
                {
                    property: 'ingested_event',
                    task: ActivationTask.IngestFirstEvent,
                },
                {
                    property: 'autocapture_web_vitals_opt_in',
                    task: ActivationTask.SetUpWebVitals,
                },
                {
                    property: 'app_urls',
                    task: ActivationTask.AddAuthorizedDomain,
                },
            ]

            teamPropertiesToCheck.forEach(({ property, task }) => {
                if (team?.[property]) {
                    actions.markTaskAsCompleted(task)
                }
            })
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadCurrentTeam() // TRICKY: Product intents are not available without loading the current team

        if (values.currentTeam) {
            actions.onTeamLoad(values.currentTeam)
        }

        // Auto-expand first available task with content
        if (!values.expandedTaskId) {
            const firstAvailableTask = values.activeTasks.find(
                (task) => !task.completed && !task.skipped && !task.lockedReason
            )
            if (firstAvailableTask) {
                actions.setExpandedTaskId(firstAvailableTask.id)
            }
        }
    }),
    permanentlyMount(),
])

export enum ActivationTask {
    // Quick Start
    IngestFirstEvent = 'ingest_first_event',
    InviteTeamMember = 'invite_team_member',
    SetUpReverseProxy = 'set_up_reverse_proxy',

    // Product Analytics
    CreateFirstInsight = 'create_first_insight',
    CreateFirstDashboard = 'create_first_dashboard',
    TrackCustomEvents = 'track_custom_events',

    // Web Analytics
    AddAuthorizedDomain = 'add_authorized_domain',
    SetUpWebVitals = 'set_up_web_vitals',

    // Session Replay
    SetupSessionRecordings = 'setup_session_recordings',
    WatchSessionRecording = 'watch_session_recording',

    // Feature Flags
    CreateFeatureFlag = 'create_feature_flag',
    UpdateFeatureFlagReleaseConditions = 'update_feature_flag_release_conditions',

    // Experiments
    LaunchExperiment = 'launch_experiment',

    // Data Warehouse
    ConnectSource = 'connect_source',

    // Surveys
    LaunchSurvey = 'launch_survey',
    CollectSurveyResponses = 'collect_survey_responses',
}

export enum ActivationSection {
    QuickStart = 'quick_start',
    ProductAnalytics = 'product_analytics',
    WebAnalytics = 'web_analytics',
    SessionReplay = 'session_replay',
    FeatureFlags = 'feature_flags',
    Experiments = 'experiments',
    DataWarehouse = 'data_warehouse',
    Surveys = 'surveys',
}

export const ACTIVATION_SECTIONS: Record<ActivationSection, { title: string; icon: ReactNode }> = {
    [ActivationSection.QuickStart]: {
        title: 'Get Started',
        icon: <IconFeatures className="w-5 h-5 text-accent" />,
    },
    [ActivationSection.ProductAnalytics]: {
        title: 'Product analytics',
        icon: <IconGraph className="w-5 h-5" color={availableOnboardingProducts.product_analytics.iconColor} />,
    },
    [ActivationSection.WebAnalytics]: {
        title: 'Web analytics',
        icon: <IconPieChart className="w-5 h-5" color={availableOnboardingProducts.web_analytics.iconColor} />,
    },
    [ActivationSection.SessionReplay]: {
        title: 'Session replay',
        icon: (
            <IconRewindPlay
                className="w-5 h-5 text-brand-yellow"
                color={availableOnboardingProducts.session_replay.iconColor}
            />
        ),
    },
    [ActivationSection.FeatureFlags]: {
        title: 'Feature flags',
        icon: (
            <IconToggle className="w-5 h-5 text-seagreen" color={availableOnboardingProducts.feature_flags.iconColor} />
        ),
    },
    [ActivationSection.Experiments]: {
        title: 'Experiments',
        icon: (
            <IconTestTube className="w-5 h-5 text-purple" color={availableOnboardingProducts.experiments.iconColor} />
        ),
    },
    [ActivationSection.DataWarehouse]: {
        title: 'Data warehouse',
        icon: (
            <IconDatabase className="w-5 h-5 text-lilac" color={availableOnboardingProducts.data_warehouse.iconColor} />
        ),
    },
    [ActivationSection.Surveys]: {
        title: 'Surveys',
        icon: <IconMessage className="w-5 h-5 text-salmon" color={availableOnboardingProducts.surveys.iconColor} />,
    },
}

export const ACTIVATION_TASKS: ActivationTaskDefinition[] = [
    // Quick Start
    {
        id: ActivationTask.IngestFirstEvent,
        title: 'Ingest your first event',
        canSkip: false,
        section: ActivationSection.QuickStart,
        buttonText: 'Install PostHog',
    },
    {
        id: ActivationTask.InviteTeamMember,
        title: 'Invite a team member',
        canSkip: true,
        section: ActivationSection.QuickStart,
        buttonText: 'Invite teammate',
    },
    {
        id: ActivationTask.SetUpReverseProxy,
        title: 'Set up a reverse proxy',
        canSkip: true,
        section: ActivationSection.QuickStart,
        url: 'https://posthog.com/docs/advanced/proxy',
        buttonText: 'Set up proxy',
    },

    // Product Analytics
    {
        id: ActivationTask.CreateFirstInsight,
        title: 'Create your first insight',
        canSkip: false,
        section: ActivationSection.ProductAnalytics,
        buttonText: 'Create insight',
    },
    {
        id: ActivationTask.CreateFirstDashboard,
        title: 'Create your first dashboard',
        canSkip: false,
        section: ActivationSection.ProductAnalytics,
        buttonText: 'Create dashboard',
    },
    {
        id: ActivationTask.TrackCustomEvents,
        title: 'Track custom events',
        canSkip: true,
        section: ActivationSection.ProductAnalytics,
        url: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
        buttonText: 'Track events',
    },

    // Web Analytics
    {
        id: ActivationTask.AddAuthorizedDomain,
        title: 'Add an authorized domain',
        canSkip: false,
        section: ActivationSection.WebAnalytics,
        buttonText: 'Add domain',
    },
    {
        id: ActivationTask.SetUpWebVitals,
        title: 'Set up web vitals',
        canSkip: true,
        section: ActivationSection.WebAnalytics,
        buttonText: 'Set up vitals',
    },

    // Sesion Replay
    {
        id: ActivationTask.SetupSessionRecordings,
        title: 'Set up session recordings',
        canSkip: false,
        section: ActivationSection.SessionReplay,
        buttonText: 'Enable recordings',
    },
    {
        id: ActivationTask.WatchSessionRecording,
        title: 'Watch a session recording',
        canSkip: false,
        section: ActivationSection.SessionReplay,
        dependsOn: [
            {
                task: ActivationTask.SetupSessionRecordings,
                reason: 'Set up session recordings first',
            },
        ],
        buttonText: 'Watch recording',
    },

    // Feature Flags
    {
        id: ActivationTask.CreateFeatureFlag,
        section: ActivationSection.FeatureFlags,
        title: 'Create a feature flag',
        canSkip: false,
        buttonText: 'Create flag',
    },
    {
        id: ActivationTask.UpdateFeatureFlagReleaseConditions,
        section: ActivationSection.FeatureFlags,
        title: 'Update release conditions',
        canSkip: false,
        dependsOn: [
            {
                task: ActivationTask.CreateFeatureFlag,
                reason: 'Create a feature flag first',
            },
        ],
        buttonText: 'Update conditions',
    },

    // Experiments
    {
        id: ActivationTask.LaunchExperiment,
        section: ActivationSection.Experiments,
        title: 'Launch an experiment',
        canSkip: false,
        buttonText: 'Launch experiment',
    },

    // Data Warehouse
    {
        id: ActivationTask.ConnectSource,
        title: 'Connect external data source',
        canSkip: false,
        section: ActivationSection.DataWarehouse,
        buttonText: 'Connect source',
    },

    // Surveys
    {
        id: ActivationTask.LaunchSurvey,
        title: 'Launch a survey',
        canSkip: false,
        section: ActivationSection.Surveys,
        buttonText: 'Launch survey',
    },
    {
        id: ActivationTask.CollectSurveyResponses,
        title: 'Collect survey responses',
        canSkip: false,
        section: ActivationSection.Surveys,
        dependsOn: [
            {
                task: ActivationTask.LaunchSurvey,
                reason: 'Launch a survey first',
            },
        ],
        buttonText: 'View responses',
    },
]

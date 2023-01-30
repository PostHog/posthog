import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/v2/types'
import { API, MOBILE, BACKEND, WEB, thirdPartySources, THIRD_PARTY, ThirdPartySource } from './constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { windowValues } from 'kea-window-values'
import { billingLogic } from 'scenes/billing/billingLogic'
import { subscriptions } from 'kea-subscriptions'
import { BillingType, TeamType } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import type { ingestionLogicV2Type } from './ingestionLogicV2Type'
import api from 'lib/api'
import { loaders } from 'kea-loaders'

export enum INGESTION_STEPS {
    START = 'Get started',
    PLATFORM = 'Select your platform',
    CONNECT_PRODUCT = 'Connect your product',
    RECORDINGS = 'Setup session recordings',
    VERIFY = 'Listen for events',
    BILLING = 'Add payment method',
    DONE = 'Done!',
}

export enum INGESTION_STEPS_WITHOUT_BILLING {
    START = 'Get started',
    PLATFORM = 'Select your platform',
    CONNECT_PRODUCT = 'Connect your product',
    RECORDINGS = 'Setup session recordings',
    VERIFY = 'Listen for events',
    DONE = 'Done!',
}

export enum INGESTION_VIEWS {
    BILLING = 'billing',
    RECORDINGS = 'recordings',
    INVITE_TEAM = 'invite-team',
    TEAM_INVITED = 'post-invite-team',
    CHOOSE_PLATFORM = 'choose-platform',
    VERIFICATION = 'verification',
    WEB_INSTRUCTIONS = 'web-instructions',
    CHOOSE_FRAMEWORK = 'choose-framework',
    GENERATING_DEMO_DATA = 'generating-demo-data',
    CHOOSE_THIRD_PARTY = 'choose-third-party',
    NO_DEMO_INGESTION = 'no-demo-ingestion',
}

export const INGESTION_VIEW_TO_STEP = {
    [INGESTION_VIEWS.BILLING]: INGESTION_STEPS.BILLING,
    [INGESTION_VIEWS.RECORDINGS]: INGESTION_STEPS.RECORDINGS,
    [INGESTION_VIEWS.INVITE_TEAM]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.TEAM_INVITED]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.NO_DEMO_INGESTION]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.CHOOSE_PLATFORM]: INGESTION_STEPS.PLATFORM,
    [INGESTION_VIEWS.VERIFICATION]: INGESTION_STEPS.VERIFY,
    [INGESTION_VIEWS.WEB_INSTRUCTIONS]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_FRAMEWORK]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.GENERATING_DEMO_DATA]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_THIRD_PARTY]: INGESTION_STEPS.CONNECT_PRODUCT,
}

export type IngestionState = {
    platform: PlatformType
    framework: Framework
    readyToVerify: boolean
    showRecording: boolean
    showBilling: boolean
    hasInvitedMembers: boolean | null
    isTechnicalUser: boolean | null
    isDemoProject: boolean | null
    generatingDemoData: boolean | null
}

const viewToState = (view: string, props: IngestionState): IngestionState => {
    switch (view) {
        case INGESTION_VIEWS.INVITE_TEAM:
            return {
                isTechnicalUser: null,
                hasInvitedMembers: null,
                platform: null,
                framework: null,
                readyToVerify: false,
                showRecording: false,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
        case INGESTION_VIEWS.TEAM_INVITED:
            return {
                isTechnicalUser: false,
                hasInvitedMembers: true,
                platform: null,
                framework: null,
                readyToVerify: false,
                showRecording: false,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
        case INGESTION_VIEWS.BILLING:
            return {
                isTechnicalUser: null,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: props.framework,
                readyToVerify: false,
                showRecording: false,
                showBilling: true,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
        case INGESTION_VIEWS.BILLING:
            return {
                isTechnicalUser: null,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: props.framework,
                readyToVerify: false,
                showRecording: true,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
        case INGESTION_VIEWS.VERIFICATION:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: props.framework,
                readyToVerify: true,
                showRecording: false,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
        case INGESTION_VIEWS.CHOOSE_PLATFORM:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: null,
                framework: null,
                readyToVerify: false,
                showRecording: false,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }

        case INGESTION_VIEWS.CHOOSE_FRAMEWORK:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: null,
                readyToVerify: false,
                showRecording: false,
                showBilling: false,
                isDemoProject: props.isDemoProject,
                generatingDemoData: false,
            }
    }
    return {
        isTechnicalUser: null,
        hasInvitedMembers: null,
        platform: null,
        framework: null,
        readyToVerify: false,
        showRecording: false,
        showBilling: false,
        isDemoProject: props.isDemoProject,
        generatingDemoData: false,
    }
}

export const ingestionLogicV2 = kea<ingestionLogicV2Type>([
    path(['scenes', 'ingestion', 'ingestionLogicV2']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            preflightLogic,
            ['preflight'],
            inviteLogic,
            ['isInviteModalShown'],
        ],
        actions: [
            teamLogic,
            ['updateCurrentTeamSuccess', 'createTeamSuccess'],
            inviteLogic,
            ['inviteTeamMembersSuccess'],
        ],
    }),
    actions({
        setState: ({
            isTechnicalUser,
            hasInvitedMembers,
            platform,
            framework,
            readyToVerify,
            showBilling,
            isDemoProject,
            generatingDemoData,
        }: IngestionState) => ({
            isTechnicalUser,
            hasInvitedMembers,
            platform,
            framework,
            readyToVerify,
            showBilling,
            isDemoProject,
            generatingDemoData,
        }),
        setActiveTab: (tab: string) => ({ tab }),
        setInstructionsModal: (isOpen: boolean) => ({ isOpen }),
        setThirdPartySource: (sourceIndex: number) => ({ sourceIndex }),
        openThirdPartyPluginModal: (plugin: PluginTypeWithConfig) => ({ plugin }),
        completeOnboarding: true,
        setCurrentStep: (currentStep: string) => ({ currentStep }),
        sidebarStepClick: (step: string) => ({ step }),
        next: (props: Partial<IngestionState>) => props,
        onBack: true,
        goToView: (view: INGESTION_VIEWS) => ({ view }),
        setSidebarSteps: (steps: string[]) => ({ steps }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
    }),
    windowValues({
        isSmallScreen: (window: Window) => window.innerWidth < getBreakpoint('md'),
    }),
    reducers({
        isTechnicalUser: [
            null as null | boolean,
            {
                setState: (_, { isTechnicalUser }) => isTechnicalUser,
            },
        ],
        hasInvitedMembers: [
            null as null | boolean,
            {
                setState: (_, { hasInvitedMembers }) => hasInvitedMembers,
            },
        ],
        platform: [
            null as null | PlatformType,
            {
                setState: (_, { platform }) => platform,
            },
        ],
        framework: [
            null as null | Framework,
            {
                setState: (_, { framework }) => (framework ? (framework.toUpperCase() as Framework) : null),
            },
        ],
        readyToVerify: [
            false,
            {
                setState: (_, { readyToVerify }) => readyToVerify,
            },
        ],
        showBilling: [
            false,
            {
                setState: (_, { showBilling }) => showBilling,
            },
        ],
        activeTab: [
            'browser',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        instructionsModalOpen: [
            false as boolean,
            {
                setInstructionsModal: (_, { isOpen }) => isOpen,
                openThirdPartyPluginModal: () => true,
            },
        ],
        thirdPartyIntegrationSource: [
            null as ThirdPartySource | null,
            {
                setThirdPartySource: (_, { sourceIndex }) => thirdPartySources[sourceIndex],
            },
        ],
        thirdPartyPluginSource: [
            null as PluginTypeWithConfig | null,
            {
                openThirdPartyPluginModal: (_, { plugin }) => plugin,
            },
        ],
        sidebarSteps: [
            Object.values(INGESTION_STEPS_WITHOUT_BILLING) as string[],
            {
                setSidebarSteps: (_, { steps }) => steps,
            },
        ],
        isDemoProject: [
            teamLogic.values.currentTeam?.is_demo as null | boolean,
            {
                setState: (_, { isDemoProject }) => isDemoProject,
            },
        ],
        generatingDemoData: [
            false as boolean | null,
            {
                setState: (_, { generatingDemoData }) => generatingDemoData,
            },
        ],
        pollTimeout: [
            0,
            {
                setPollTimeout: (_, payload) => payload.pollTimeout,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        isDemoDataReady: [
            false as boolean,
            {
                checkIfDemoDataIsReady: async (_, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(values.pollTimeout)

                    try {
                        const res = await api.get('api/projects/@current/is_generating_demo_data')
                        if (!res.is_generating_demo_data) {
                            return true
                        }
                        const pollTimeoutMilliseconds = 1000
                        const timeout = window.setTimeout(actions.checkIfDemoDataIsReady, pollTimeoutMilliseconds)
                        actions.setPollTimeout(timeout)
                        return false
                    } catch (e) {
                        return false
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        currentState: [
            (s) => [
                s.platform,
                s.framework,
                s.readyToVerify,
                s.showBilling,
                s.isTechnicalUser,
                s.hasInvitedMembers,
                s.isDemoProject,
                s.generatingDemoData,
            ],
            (
                platform,
                framework,
                readyToVerify,
                showBilling,
                isTechnicalUser,
                hasInvitedMembers,
                isDemoProject,
                generatingDemoData
            ) => ({
                platform,
                framework,
                readyToVerify,
                showBilling,
                isTechnicalUser,
                hasInvitedMembers,
                isDemoProject,
                generatingDemoData,
            }),
        ],
        currentView: [
            (s) => [s.currentState],
            ({
                isTechnicalUser,
                platform,
                framework,
                readyToVerify,
                showBilling,
                hasInvitedMembers,
                isDemoProject,
                generatingDemoData,
            }) => {
                if (isDemoProject) {
                    return INGESTION_VIEWS.NO_DEMO_INGESTION
                }
                if (showBilling) {
                    return INGESTION_VIEWS.BILLING
                }
                if (readyToVerify) {
                    return INGESTION_VIEWS.VERIFICATION
                }

                if (isTechnicalUser) {
                    if (!platform) {
                        return INGESTION_VIEWS.CHOOSE_PLATFORM
                    }
                    if (framework || platform === WEB) {
                        return INGESTION_VIEWS.WEB_INSTRUCTIONS
                    }
                    if (platform === MOBILE || platform === BACKEND) {
                        return INGESTION_VIEWS.CHOOSE_FRAMEWORK
                    }
                    if (platform === THIRD_PARTY) {
                        return INGESTION_VIEWS.CHOOSE_THIRD_PARTY
                    }
                    // could be null, so we check that it's set to false
                } else if (isTechnicalUser === false) {
                    if (generatingDemoData) {
                        return INGESTION_VIEWS.GENERATING_DEMO_DATA
                    }
                    if (hasInvitedMembers) {
                        return INGESTION_VIEWS.TEAM_INVITED
                    }
                    if (!platform && !readyToVerify) {
                        return INGESTION_VIEWS.INVITE_TEAM
                    }
                }

                return INGESTION_VIEWS.INVITE_TEAM
            },
        ],
        currentStep: [
            (s) => [s.currentView],
            (currentView) => {
                return INGESTION_VIEW_TO_STEP[currentView]
            },
        ],
        previousStep: [
            (s) => [s.currentStep],
            (currentStep) => {
                const currentStepIndex = Object.values(INGESTION_STEPS).indexOf(currentStep)
                return Object.values(INGESTION_STEPS)[currentStepIndex - 1]
            },
        ],
        frameworkString: [
            (s) => [s.framework],
            (framework): string => {
                if (framework) {
                    const frameworkStrings = {
                        NODEJS: 'Node.js',
                        GO: 'Go',
                        RUBY: 'Ruby',
                        PYTHON: 'Python',
                        PHP: 'PHP',
                        ELIXIR: 'Elixir',
                        ANDROID: 'Android',
                        IOS: 'iOS',
                        REACT_NATIVE: 'React Native',
                        FLUTTER: 'Flutter',
                        API: 'HTTP API',
                    }
                    return frameworkStrings[framework] || framework
                }
                return ''
            },
        ],
        showBillingStep: [
            (s) => [s.preflight],
            (preflight): boolean => {
                return !!preflight?.cloud && !preflight?.demo
            },
        ],
    })),

    actionToUrl(({ values }) => ({
        setState: () => getUrl(values),
        updateCurrentTeamSuccess: () => {
            if (router.values.location.pathname.includes('/ingestion')) {
                return combineUrl(urls.events(), { onboarding_completed: true }).url
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/ingestion': () => actions.goToView(INGESTION_VIEWS.INVITE_TEAM),
        '/ingestion/invites-sent': () => actions.goToView(INGESTION_VIEWS.TEAM_INVITED),
        '/ingestion/billing': () => actions.goToView(INGESTION_VIEWS.BILLING),
        '/ingestion/verify': () => actions.goToView(INGESTION_VIEWS.VERIFICATION),
        '/ingestion/platform': () => actions.goToView(INGESTION_VIEWS.CHOOSE_FRAMEWORK),
        '/ingestion(/:platform)(/:framework)': (pathParams, searchParams) => {
            const platform = pathParams.platform || searchParams.platform || null
            const framework = pathParams.framework || searchParams.framework || null
            actions.setState({
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: platform,
                framework: framework,
                readyToVerify: false,
                showBilling: false,
                showRecording: false,
                isDemoProject: values.isDemoProject,
                generatingDemoData: false,
            })
        },
    })),
    listeners(({ actions, values }) => ({
        next: (props) => {
            actions.setState({ ...values.currentState, ...props } as IngestionState)
        },
        goToView: ({ view }) => {
            actions.setState(viewToState(view, values.currentState as IngestionState))
        },
        completeOnboarding: () => {
            teamLogic.actions.updateCurrentTeam({
                completed_snippet_onboarding: true,
            })
        },
        openThirdPartyPluginModal: ({ plugin }) => {
            pluginsLogic.actions.editPlugin(plugin.id)
        },
        setPlatform: ({ platform }) => {
            eventUsageLogic.actions.reportIngestionSelectPlatformType(platform)
        },
        setFramework: ({ framework }) => {
            eventUsageLogic.actions.reportIngestionSelectFrameworkType(framework)
        },
        sidebarStepClick: ({ step }) => {
            switch (step) {
                case INGESTION_STEPS.START:
                    actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
                    return
                case INGESTION_STEPS.PLATFORM:
                    actions.goToView(INGESTION_VIEWS.CHOOSE_PLATFORM)
                    return
                case INGESTION_STEPS.CONNECT_PRODUCT:
                    actions.goToView(INGESTION_VIEWS.CHOOSE_FRAMEWORK)
                    return
                case INGESTION_STEPS.VERIFY:
                    actions.goToView(INGESTION_VIEWS.VERIFICATION)
                    return
                case INGESTION_STEPS.BILLING:
                    actions.goToView(INGESTION_VIEWS.BILLING)
                    return
                default:
                    return
            }
        },
        onBack: () => {
            switch (values.currentView) {
                case INGESTION_VIEWS.BILLING:
                    return actions.goToView(INGESTION_VIEWS.VERIFICATION)
                case INGESTION_VIEWS.TEAM_INVITED:
                    return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
                case INGESTION_VIEWS.CHOOSE_PLATFORM:
                    return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
                case INGESTION_VIEWS.VERIFICATION:
                    return actions.goToView(INGESTION_VIEWS.CHOOSE_FRAMEWORK)
                case INGESTION_VIEWS.WEB_INSTRUCTIONS:
                    return actions.goToView(INGESTION_VIEWS.CHOOSE_PLATFORM)
                case INGESTION_VIEWS.CHOOSE_FRAMEWORK:
                    return actions.goToView(INGESTION_VIEWS.CHOOSE_PLATFORM)
                // If they're on the InviteTeam step, but on the Team Invited panel,
                // we still want them to be able to go back to the previous step.
                // So this resets the state for that panel so they can go back.
                case INGESTION_VIEWS.INVITE_TEAM:
                    return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
                case INGESTION_VIEWS.CHOOSE_THIRD_PARTY:
                    return actions.goToView(INGESTION_VIEWS.CHOOSE_PLATFORM)
                default:
                    return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
            }
        },
        inviteTeamMembersSuccess: () => {
            if (router.values.location.pathname.includes(urls.ingestion())) {
                actions.setState(viewToState(INGESTION_VIEWS.TEAM_INVITED, values.currentState as IngestionState))
            }
        },
        createTeamSuccess: ({ currentTeam }) => {
            if (window.location.href.includes(urls.ingestion()) && currentTeam.is_demo) {
                actions.checkIfDemoDataIsReady(null)
            } else {
                window.location.href = urls.ingestion()
            }
        },
        checkIfDemoDataIsReadySuccess: ({ isDemoDataReady }) => {
            if (isDemoDataReady) {
                window.location.href = urls.default()
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        showBillingStep: (value) => {
            const steps = value ? INGESTION_STEPS : INGESTION_STEPS_WITHOUT_BILLING
            actions.setSidebarSteps(Object.values(steps))
        },
        billing: (billing: BillingType) => {
            if (billing?.plan && values.showBilling) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
        currentTeam: (currentTeam: TeamType) => {
            if (currentTeam?.ingested_event && values.readyToVerify && !values.showBillingStep) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
    })),
])

function getUrl(values: ingestionLogicV2Type['values']): string | [string, Record<string, undefined | string>] {
    const { isTechnicalUser, platform, framework, readyToVerify, showBilling, hasInvitedMembers, generatingDemoData } =
        values

    let url = '/ingestion'

    if (showBilling) {
        return url + '/billing'
    }

    if (readyToVerify) {
        url += '/verify'
        return [
            url,
            {
                platform: platform || undefined,
                framework: framework?.toLowerCase() || undefined,
            },
        ]
    }

    if (isTechnicalUser) {
        if (framework === API) {
            url += '/api'
            return [
                url,
                {
                    platform: platform || undefined,
                },
            ]
        }

        if (platform === MOBILE) {
            url += '/mobile'
        }

        if (platform === WEB) {
            url += '/web'
        }

        if (platform === BACKEND) {
            url += '/backend'
        }

        if (generatingDemoData) {
            url += '/just-exploring'
        }

        if (platform === THIRD_PARTY) {
            url += '/third-party'
        }

        if (!platform) {
            url += '/platform'
        }

        if (framework) {
            url += `/${framework.toLowerCase()}`
        }
    } else {
        if (!platform && hasInvitedMembers) {
            url += '/invites-sent'
        }
    }

    return url
}

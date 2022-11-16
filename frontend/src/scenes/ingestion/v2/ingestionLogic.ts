import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/v2/types'
import { API, MOBILE, BACKEND, WEB, BOOKMARKLET, thirdPartySources, THIRD_PARTY, ThirdPartySource } from './constants'
import type { ingestionLogicV2Type } from './ingestionLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { windowValues } from 'kea-window-values'
import { billingLogic } from 'scenes/billing/billingLogic'
import { subscriptions } from 'kea-subscriptions'
import { BillingType, TeamType } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'

export enum INGESTION_STEPS {
    START = 'Get started',
    PLATFORM = 'Select your platform',
    CONNECT_PRODUCT = 'Connect your product',
    VERIFY = 'Listen for events',
    BILLING = 'Add payment method',
    DONE = 'Done!',
}

export enum INGESTION_STEPS_WITHOUT_BILLING {
    START = 'Get started',
    PLATFORM = 'Select your platform',
    CONNECT_PRODUCT = 'Connect your product',
    VERIFY = 'Listen for events',
    DONE = 'Done!',
}

export enum INGESTION_VIEWS {
    BILLING = 'billing',
    INVITE_TEAM = 'invite-team',
    TEAM_INVITED = 'post-invite-team',
    CHOOSE_PLATFORM = 'choose-platform',
    VERIFICATION = 'verification',
    WEB_INSTRUCTIONS = 'web-instructions',
    CHOOSE_FRAMEWORK = 'choose-framework',
    BOOKMARKLET = 'bookmarklet',
    CHOOSE_THIRD_PARTY = 'choose-third-party',
}

export const INGESTION_VIEW_TO_STEP = {
    [INGESTION_VIEWS.BILLING]: INGESTION_STEPS.BILLING,
    [INGESTION_VIEWS.INVITE_TEAM]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.TEAM_INVITED]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.CHOOSE_PLATFORM]: INGESTION_STEPS.PLATFORM,
    [INGESTION_VIEWS.VERIFICATION]: INGESTION_STEPS.VERIFY,
    [INGESTION_VIEWS.WEB_INSTRUCTIONS]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_FRAMEWORK]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.BOOKMARKLET]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_THIRD_PARTY]: INGESTION_STEPS.CONNECT_PRODUCT,
}

export type IngestionState = {
    platform: PlatformType
    framework: Framework
    readyToVerify: boolean
    showBilling: boolean
    hasInvitedMembers: boolean | null
    isTechnicalUser: boolean | null
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
                showBilling: false,
            }
        case INGESTION_VIEWS.TEAM_INVITED:
            return {
                isTechnicalUser: false,
                hasInvitedMembers: true,
                platform: null,
                framework: null,
                readyToVerify: false,
                showBilling: false,
            }
        case INGESTION_VIEWS.BILLING:
            return {
                isTechnicalUser: null,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: props.framework,
                readyToVerify: false,
                showBilling: true,
            }
        case INGESTION_VIEWS.VERIFICATION:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: props.framework,
                readyToVerify: true,
                showBilling: false,
            }
        case INGESTION_VIEWS.CHOOSE_PLATFORM:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: null,
                framework: null,
                readyToVerify: false,
                showBilling: false,
            }

        case INGESTION_VIEWS.CHOOSE_FRAMEWORK:
            return {
                isTechnicalUser: true,
                hasInvitedMembers: null,
                platform: props.platform,
                framework: null,
                readyToVerify: false,
                showBilling: false,
            }
    }
    return {
        isTechnicalUser: null,
        hasInvitedMembers: null,
        platform: null,
        framework: null,
        readyToVerify: false,
        showBilling: false,
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
        actions: [teamLogic, ['updateCurrentTeamSuccess'], inviteLogic, ['inviteTeamMembersSuccess']],
    }),
    actions({
        setState: ({
            isTechnicalUser,
            hasInvitedMembers,
            platform,
            framework,
            readyToVerify,
            showBilling,
        }: IngestionState) => ({
            isTechnicalUser,
            hasInvitedMembers,
            platform,
            framework,
            readyToVerify,
            showBilling,
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
    }),
    selectors(() => ({
        currentState: [
            (s) => [s.platform, s.framework, s.readyToVerify, s.showBilling, s.isTechnicalUser, s.hasInvitedMembers],
            (platform, framework, readyToVerify, showBilling, isTechnicalUser, hasInvitedMembers) => ({
                platform,
                framework,
                readyToVerify,
                showBilling,
                isTechnicalUser,
                hasInvitedMembers,
            }),
        ],
        currentView: [
            (s) => [s.currentState],
            ({ isTechnicalUser, platform, framework, readyToVerify, showBilling, hasInvitedMembers }) => {
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
                    if (hasInvitedMembers) {
                        return INGESTION_VIEWS.TEAM_INVITED
                    }
                    if (!platform && !readyToVerify) {
                        return INGESTION_VIEWS.INVITE_TEAM
                    }
                    if (platform === BOOKMARKLET) {
                        return INGESTION_VIEWS.BOOKMARKLET
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
                return urls.events()
            }
        },
    })),

    urlToAction(({ actions }) => ({
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
                case INGESTION_VIEWS.BOOKMARKLET:
                    if (values.hasInvitedMembers) {
                        return actions.goToView(INGESTION_VIEWS.TEAM_INVITED)
                    } else {
                        return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
                    }
                case INGESTION_VIEWS.CHOOSE_THIRD_PARTY:
                    return actions.goToView(INGESTION_VIEWS.CHOOSE_PLATFORM)
                default:
                    return actions.goToView(INGESTION_VIEWS.INVITE_TEAM)
            }
        },
        inviteTeamMembersSuccess: () => {
            if (router.values.location.pathname.includes('/ingestion')) {
                actions.setState({ ...values.currentState, hasInvitedMembers: true } as IngestionState)
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
    const { isTechnicalUser, platform, framework, readyToVerify, showBilling, hasInvitedMembers } = values

    let url = '/ingestion'

    if (showBilling) {
        return url + '/billing'
    }

    if (isTechnicalUser) {
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

        if (platform === BOOKMARKLET) {
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
        if (!platform && isTechnicalUser && hasInvitedMembers) {
            url += '/invites-sent'
        }
    }

    return url
}

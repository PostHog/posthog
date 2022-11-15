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
    POST_INVITE_TEAM = 'post-invite-team',
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
    [INGESTION_VIEWS.POST_INVITE_TEAM]: INGESTION_STEPS.START,
    [INGESTION_VIEWS.CHOOSE_PLATFORM]: INGESTION_STEPS.PLATFORM,
    [INGESTION_VIEWS.VERIFICATION]: INGESTION_STEPS.VERIFY,
    [INGESTION_VIEWS.WEB_INSTRUCTIONS]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_FRAMEWORK]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.BOOKMARKLET]: INGESTION_STEPS.CONNECT_PRODUCT,
    [INGESTION_VIEWS.CHOOSE_THIRD_PARTY]: INGESTION_STEPS.CONNECT_PRODUCT,
}

const stringToPlatformType = (
    platform: string | null,
    allowed: string[] = ['mobile', 'web', 'backend', 'just-exploring', 'third-party']
): PlatformType | null => {
    if (!platform || !allowed.includes(platform)) {
        return null
    }
    return platform === 'mobile'
        ? MOBILE
        : platform === 'web'
        ? WEB
        : platform === 'backend'
        ? BACKEND
        : platform === 'just-exploring'
        ? BOOKMARKLET
        : platform === 'third-party'
        ? THIRD_PARTY
        : null
}

export const ingestionLogicV2 = kea<ingestionLogicV2Type>([
    path(['scenes', 'ingestion', 'ingestionLogic']),
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
        setTechnical: (technical: boolean) => ({ technical }),
        setHasInvitedMembers: (hasInvitedMembers: boolean) => ({ hasInvitedMembers }),
        setPlatform: (platform: PlatformType) => ({ platform }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setAddBilling: (addBilling: boolean) => ({ addBilling }),
        setState: ({
            technical,
            hasInvitedMembers,
            platform,
            framework,
            verify,
            addBilling,
        }: {
            technical: boolean | null
            hasInvitedMembers: boolean | null
            platform: PlatformType
            framework: string | null
            verify: boolean
            addBilling: boolean
        }) => ({
            technical,
            hasInvitedMembers,
            platform,
            framework,
            verify,
            addBilling,
        }),
        setActiveTab: (tab: string) => ({ tab }),
        setInstructionsModal: (isOpen: boolean) => ({ isOpen }),
        setThirdPartySource: (sourceIndex: number) => ({ sourceIndex }),
        openThirdPartyPluginModal: (plugin: PluginTypeWithConfig) => ({ plugin }),
        completeOnboarding: true,
        setCurrentStep: (currentStep: string) => ({ currentStep }),
        sidebarStepClick: (step: string) => ({ step }),
        onBack: true,
        setSidebarSteps: (steps: string[]) => ({ steps }),
    }),
    windowValues({
        isSmallScreen: (window: Window) => window.innerWidth < getBreakpoint('md'),
    }),
    reducers({
        technical: [
            null as null | boolean,
            {
                setTechnical: (_, { technical }) => technical,
                setState: (_, { technical }) => technical,
            },
        ],
        hasInvitedMembers: [
            null as null | boolean,
            {
                setHasInvitedMembers: (_, { hasInvitedMembers }) => hasInvitedMembers,
                setState: (_, { hasInvitedMembers }) => hasInvitedMembers,
            },
        ],
        platform: [
            null as null | PlatformType,
            {
                setPlatform: (_, { platform }) => platform,
                setState: (_, { platform }) => platform,
            },
        ],
        framework: [
            null as null | Framework,
            {
                setFramework: (_, { framework }) => framework as Framework,
                setState: (_, { framework }) => (framework ? (framework.toUpperCase() as Framework) : null),
            },
        ],
        verify: [
            false,
            {
                setPlatform: () => false,
                setFramework: () => false,
                setAddBilling: () => false,
                setTechnical: () => false,
                setVerify: (_, { verify }) => verify,
                setState: (_, { verify }) => verify,
            },
        ],
        addBilling: [
            false,
            {
                setPlatform: () => false,
                setFramework: () => false,
                setVerify: () => false,
                setTechnical: () => false,
                setAddBilling: (_, { addBilling }) => addBilling,
                setState: (_, { addBilling }) => addBilling,
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
        currentView: [
            (s) => [
                s.technical,
                s.platform,
                s.framework,
                s.verify,
                s.addBilling,
                s.hasInvitedMembers,
                s.isInviteModalShown,
            ],
            (technical, platform, framework, verify, addBilling, hasInvitedMembers, isInviteModalShown) => {
                if (addBilling) {
                    return INGESTION_VIEWS.BILLING
                }

                if (hasInvitedMembers && !isInviteModalShown && !technical) {
                    return INGESTION_VIEWS.POST_INVITE_TEAM
                }

                if (!platform && !verify && !technical) {
                    return INGESTION_VIEWS.INVITE_TEAM
                }

                if (!platform && !verify && technical) {
                    return INGESTION_VIEWS.CHOOSE_PLATFORM
                }

                if (verify) {
                    return INGESTION_VIEWS.VERIFICATION
                }

                if (framework || platform === WEB) {
                    return INGESTION_VIEWS.WEB_INSTRUCTIONS
                }

                if (platform === MOBILE || platform === BACKEND) {
                    return INGESTION_VIEWS.CHOOSE_FRAMEWORK
                }

                if (platform === BOOKMARKLET) {
                    return INGESTION_VIEWS.BOOKMARKLET
                }

                if (platform === THIRD_PARTY) {
                    return INGESTION_VIEWS.CHOOSE_THIRD_PARTY
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
        setTechnical: () => getUrl(values),
        setHasInvitedMembers: () => getUrl(values),
        setPlatform: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
        setAddBilling: () => getUrl(values),
        setState: () => getUrl(values),
        updateCurrentTeamSuccess: () => {
            const isBillingPage = router.values.location.pathname == '/ingestion/billing'
            const isVerifyPage = !values.showBillingStep && router.values.location.pathname == '/ingestion/verify'
            if (isBillingPage || isVerifyPage) {
                return urls.events()
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/ingestion': () =>
            actions.setState({
                technical: null,
                hasInvitedMembers: null,
                platform: null,
                framework: null,
                verify: false,
                addBilling: false,
            }),
        '/ingestion/invites-sent': () =>
            actions.setState({
                technical: false,
                hasInvitedMembers: true,
                platform: null,
                framework: null,
                verify: false,
                addBilling: false,
            }),
        '/ingestion/billing': (_: any, { platform, framework }) => {
            actions.setState({
                technical: null,
                hasInvitedMembers: null,
                platform: stringToPlatformType(platform),
                framework,
                verify: false,
                addBilling: false,
            })
        },
        '/ingestion/verify': (_: any, { platform, framework }) => {
            actions.setState({
                technical: true,
                hasInvitedMembers: null,
                platform: stringToPlatformType(platform),
                framework: framework,
                verify: false,
                addBilling: false,
            })
        },
        '/ingestion/api': (_: any, { platform }) => {
            actions.setState({
                technical: true,
                hasInvitedMembers: null,
                platform: stringToPlatformType(platform, ['web', 'mobile', 'backend']),
                framework: API,
                verify: false,
                addBilling: false,
            })
        },
        '/ingestion(/:platform)(/:framework)': ({ platform, framework }) => {
            if (platform && framework) {
                actions.setState({
                    technical: true,
                    hasInvitedMembers: null,
                    platform: stringToPlatformType(platform),
                    framework,
                    verify: false,
                    addBilling: false,
                })
            }
        },
    })),
    listeners(({ actions, values }) => ({
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
                    actions.setTechnical(false)
                    return
                case INGESTION_STEPS.PLATFORM:
                    actions.setPlatform(null)
                    return
                case INGESTION_STEPS.CONNECT_PRODUCT:
                    if (values.platform) {
                        actions.setVerify(false)
                        actions.setPlatform(values.platform)
                    }
                    return
                case INGESTION_STEPS.VERIFY:
                    if (values.platform) {
                        actions.setVerify(true)
                    }
                    return
                case INGESTION_STEPS.BILLING:
                    if (values.platform) {
                        actions.setAddBilling(true)
                    }
                    return
                default:
                    return
            }
        },
        onBack: () => {
            switch (values.currentStep) {
                case INGESTION_STEPS.BILLING:
                    actions.setState({
                        technical: values.technical,
                        hasInvitedMembers: values.hasInvitedMembers,
                        platform: values.platform,
                        framework: values.framework,
                        verify: true,
                        addBilling: false,
                    })
                    return
                case INGESTION_STEPS.VERIFY:
                    actions.setState({
                        technical: values.technical,
                        hasInvitedMembers: values.hasInvitedMembers,
                        platform: values.platform,
                        framework: null,
                        verify: false,
                        addBilling: false,
                    })
                    return
                case INGESTION_STEPS.CONNECT_PRODUCT:
                    actions.setState({
                        technical: values.technical,
                        hasInvitedMembers: values.hasInvitedMembers,
                        platform: null,
                        framework: null,
                        verify: false,
                        addBilling: false,
                    })
                    return
                case INGESTION_STEPS.PLATFORM:
                    actions.setState({
                        technical: null,
                        hasInvitedMembers: null,
                        platform: null,
                        framework: null,
                        verify: false,
                        addBilling: false,
                    })
                    return
                default:
                    return
            }
        },
        inviteTeamMembersSuccess: () => {
            if (router.values.location.pathname.includes('/ingestion')) {
                actions.setHasInvitedMembers(true)
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        showBillingStep: (value) => {
            const steps = value ? INGESTION_STEPS : INGESTION_STEPS_WITHOUT_BILLING
            actions.setSidebarSteps(Object.values(steps))
        },
        billing: (billing: BillingType) => {
            if (billing?.plan && values.addBilling) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
        currentTeam: (currentTeam: TeamType) => {
            if (currentTeam?.ingested_event && values.verify && !values.showBillingStep) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
    })),
])

function getUrl(values: ingestionLogicV2Type['values']): string | [string, Record<string, undefined | string>] {
    const { technical, platform, framework, verify, addBilling, hasInvitedMembers } = values

    let url = '/ingestion'

    if (addBilling) {
        return url + '/billing'
    }

    if (verify) {
        url += '/verify'
        return [
            url,
            {
                platform: stringToPlatformType(platform) as string,
                framework: framework?.toLowerCase() || undefined,
            },
        ]
    }

    if (framework === API) {
        url += '/api'
        return [
            url,
            {
                platform: stringToPlatformType(platform, ['web', 'mobile', 'backend']) as string,
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

    if (technical && !platform) {
        url += '/platform'
    }

    if (!technical && !platform && hasInvitedMembers) {
        url += '/invites-sent'
    }

    if (framework) {
        url += `/${framework.toLowerCase()}`
    }

    return url
}

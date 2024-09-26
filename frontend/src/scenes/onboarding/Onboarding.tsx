import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS, SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { AndroidInstructions } from 'scenes/onboarding/sdks/session-replay'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ProductKey, SDKKey } from '~/types'

import { DataWarehouseSources } from './data-warehouse/sources'
import { OnboardingBillingStep } from './OnboardingBillingStep'
import { OnboardingInviteTeammates } from './OnboardingInviteTeammates'
import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'
import { OnboardingProductConfiguration } from './OnboardingProductConfiguration'
import { ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingProductIntroduction } from './OnboardingProductIntroduction'
import { OnboardingReverseProxy } from './OnboardingReverseProxy'
import { OnboardingDashboardTemplateConfigureStep } from './productAnalyticsSteps/DashboardTemplateConfigureStep'
import { OnboardingDashboardTemplateSelectStep } from './productAnalyticsSteps/DashboardTemplateSelectStep'
import { FeatureFlagsSDKInstructions } from './sdks/feature-flags/FeatureFlagsSDKInstructions'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SDKs } from './sdks/SDKs'
import { iOSInstructions } from './sdks/session-replay/ios'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'
import { SurveysSDKInstructions } from './sdks/surveys/SurveysSDKInstructions'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Wrapper for custom onboarding content. This automatically includes billing, other products, and invite steps.
 */
const OnboardingWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const {
        productKey,
        currentOnboardingStep,
        shouldShowBillingStep,
        shouldShowReverseProxyStep,
        product,
        includeIntro,
        waitForBilling,
    } = useValues(onboardingLogic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { setAllOnboardingSteps } = useActions(onboardingLogic)
    const [allSteps, setAllSteps] = useState<JSX.Element[]>([])

    useEffect(() => {
        createAllSteps()
    }, [children, billingLoading])

    useEffect(() => {
        if (!allSteps.length || (billingLoading && waitForBilling)) {
            return
        }
        setAllOnboardingSteps(allSteps)
    }, [allSteps])

    if (!product || !children) {
        return <></>
    }

    const createAllSteps = (): void => {
        let steps = []
        if (Array.isArray(children)) {
            steps = [...children]
        } else {
            steps = [children as JSX.Element]
        }
        const billingProduct = billing?.products.find((p) => p.type === productKey)
        if (includeIntro && billingProduct) {
            const IntroStep = <OnboardingProductIntroduction stepKey={OnboardingStepKey.PRODUCT_INTRO} />
            steps = [IntroStep, ...steps]
        }
        if (shouldShowReverseProxyStep) {
            const ReverseProxyStep = <OnboardingReverseProxy stepKey={OnboardingStepKey.REVERSE_PROXY} />
            steps = [...steps, ReverseProxyStep]
        }
        if (shouldShowBillingStep && billingProduct) {
            const BillingStep = <OnboardingBillingStep product={billingProduct} stepKey={OnboardingStepKey.PLANS} />
            steps = [...steps, BillingStep]
        }
        const inviteTeammatesStep = <OnboardingInviteTeammates stepKey={OnboardingStepKey.INVITE_TEAMMATES} />
        steps = [...steps, inviteTeammatesStep].filter(Boolean)
        setAllSteps(steps)
    }

    if (!currentOnboardingStep) {
        return (
            <div className="flex items-center justify-center my-20">
                <Spinner className="text-2xl text-muted w-10 h-10" />
            </div>
        )
    }

    return currentOnboardingStep || <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // mount the logic here so that it stays mounted for the entire onboarding flow
    // not sure if there is a better way to do this
    useValues(newDashboardLogic)

    const showTemplateSteps =
        featureFlags[FEATURE_FLAGS.ONBOARDING_DASHBOARD_TEMPLATES] == 'test' && window.innerWidth > 1000

    const options: ProductConfigOption[] = [
        {
            title: 'Autocapture frontend interactions',
            description: `If you use our JavaScript or React Native libraries, we'll automagically 
            capture frontend interactions like clicks, submits, and more. Fine-tune what you 
            capture directly in your code snippet.`,
            teamProperty: 'autocapture_opt_out',
            value: !currentTeam?.autocapture_opt_out,
            type: 'toggle',
            inverseToggle: true,
            visible: true,
        },
        {
            title: 'Enable heatmaps',
            description: `If you use our JavaScript libraries, we can capture general clicks, mouse movements,
                   and scrolling to create heatmaps. 
                   No additional events are created, and you can disable this at any time.`,
            teamProperty: 'heatmaps_opt_in',
            value: currentTeam?.heatmaps_opt_in ?? true,
            type: 'toggle',
            visible: true,
        },
        {
            title: 'Enable web vitals autocapture',
            description: `Uses Google's web vitals library to automagically capture performance information.`,
            teamProperty: 'autocapture_web_vitals_opt_in',
            value: currentTeam?.autocapture_web_vitals_opt_in ?? true,
            type: 'toggle',
            visible: true,
        },
        {
            title: 'Enable session recordings',
            description: `Turn on session recordings and watch how users experience your app. We will also turn on console log and network performance recording. You can change these settings any time in the settings panel.`,
            teamProperty: 'session_recording_opt_in',
            value: currentTeam?.session_recording_opt_in ?? true,
            type: 'toggle',
            visible: true,
        },
        {
            title: 'Capture console logs',
            description: `Automatically enable console log capture`,
            teamProperty: 'capture_console_log_opt_in',
            value: true,
            type: 'toggle',
            visible: false,
        },
        {
            title: 'Capture network performance',
            description: `Automatically enable network performance capture`,
            teamProperty: 'capture_performance_opt_in',
            value: true,
            type: 'toggle',
            visible: false,
        },
    ]

    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="collecting events"
                sdkInstructionMap={ProductAnalyticsSDKInstructions}
                stepKey={OnboardingStepKey.INSTALL}
            />
            <OnboardingProductConfiguration stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION} options={options} />

            {/* this is two conditionals because they need to be direct children of the wrapper */}
            {showTemplateSteps ? (
                <OnboardingDashboardTemplateSelectStep stepKey={OnboardingStepKey.DASHBOARD_TEMPLATE} />
            ) : null}
            {showTemplateSteps ? (
                <OnboardingDashboardTemplateConfigureStep stepKey={OnboardingStepKey.DASHBOARD_TEMPLATE_CONFIGURE} />
            ) : null}
        </OnboardingWrapper>
    )
}
const SessionReplayOnboarding = (): JSX.Element => {
    const { hasAvailableFeature } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const hasMobileOnBoarding = !!featureFlags[FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING]

    const configOptions: ProductConfigOption[] = [
        {
            type: 'toggle',
            title: 'Capture console logs',
            description: `Capture console logs as a part of user session recordings. 
                            Use the console logs alongside recordings to debug any issues with your app.`,
            teamProperty: 'capture_console_log_opt_in',
            value: currentTeam?.capture_console_log_opt_in ?? true,
            visible: true,
        },
        {
            type: 'toggle',
            title: 'Capture network performance',
            description: `Capture performance and network information alongside recordings. Use the
                            network requests and timings in the recording player to help you debug issues with your app.`,
            teamProperty: 'capture_performance_opt_in',
            value: currentTeam?.capture_performance_opt_in ?? true,
            visible: true,
        },
        {
            type: 'toggle',
            title: 'Record user sessions',
            description: 'Watch recordings of how users interact with your web app to see what can be improved.',
            teamProperty: 'session_recording_opt_in',
            value: true,
            visible: false,
        },
    ]

    if (hasAvailableFeature(AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM)) {
        configOptions.push({
            type: 'select',
            title: 'Minimum session duration (seconds)',
            description: `Only record sessions that are longer than the specified duration. 
                            Start with it low and increase it later if you're getting too many short sessions.`,
            teamProperty: 'session_recording_minimum_duration_milliseconds',
            value: currentTeam?.session_recording_minimum_duration_milliseconds || null,
            selectOptions: SESSION_REPLAY_MINIMUM_DURATION_OPTIONS,
            visible: true,
        })
    }

    const sdkInstructionMap = SessionReplaySDKInstructions
    if (hasMobileOnBoarding) {
        sdkInstructionMap[SDKKey.ANDROID] = AndroidInstructions
        sdkInstructionMap[SDKKey.IOS] = iOSInstructions
    }

    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="recording sessions"
                sdkInstructionMap={sdkInstructionMap}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.INSTALL}
            />
            <OnboardingProductConfiguration
                stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
                options={configOptions}
                product={ProductKey.SESSION_REPLAY}
            />
        </OnboardingWrapper>
    )
}

const FeatureFlagsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="loading flags & experiments"
                sdkInstructionMap={FeatureFlagsSDKInstructions}
                subtitle="Choose the framework where you want to use feature flags and/or run experiments, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.INSTALL}
            />
        </OnboardingWrapper>
    )
}

const SurveysOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="taking surveys"
                sdkInstructionMap={SurveysSDKInstructions}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.INSTALL}
            />
        </OnboardingWrapper>
    )
}

const DataWarehouseOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <DataWarehouseSources usersAction="Data Warehouse" stepKey={OnboardingStepKey.LINK_DATA} />
        </OnboardingWrapper>
    )
}

export const onboardingViews = {
    [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsOnboarding,
    [ProductKey.SESSION_REPLAY]: SessionReplayOnboarding,
    [ProductKey.FEATURE_FLAGS]: FeatureFlagsOnboarding,
    [ProductKey.SURVEYS]: SurveysOnboarding,
    [ProductKey.DATA_WAREHOUSE]: DataWarehouseOnboarding,
}

export function Onboarding(): JSX.Element | null {
    const { product, productKey } = useValues(onboardingLogic)

    if (!product || !productKey) {
        return <></>
    }
    const OnboardingView = onboardingViews[productKey]

    return <OnboardingView />
}

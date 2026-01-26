import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel, SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { ProductSelection } from 'scenes/onboarding/productSelection/ProductSelection'
import { productSelectionLogic } from 'scenes/onboarding/productSelection/productSelectionLogic'
import { WebAnalyticsSDKInstructions } from 'scenes/onboarding/sdks/web-analytics/WebAnalyticsSDKInstructions'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, type SessionRecordingMaskingLevel, TeamPublicType, TeamType } from '~/types'

import { OnboardingInviteTeammates } from './OnboardingInviteTeammates'
import { OnboardingProductConfiguration } from './OnboardingProductConfiguration'
import { OnboardingReverseProxy } from './OnboardingReverseProxy'
import { OnboardingSessionReplayConfiguration } from './OnboardingSessionReplayConfiguration'
import { OnboardingUpgradeStep } from './billing/OnboardingUpgradeStep'
import { OnboardingDataWarehouseSourcesStep } from './data-warehouse/OnboardingDataWarehouseSourcesStep'
import { OnboardingErrorTrackingAlertsStep } from './error-tracking/OnboardingErrorTrackingAlertsStep'
import { OnboardingErrorTrackingSourceMapsStep } from './error-tracking/OnboardingErrorTrackingSourceMapsStep'
import { OnboardingLogicProps, OnboardingStepElement, onboardingLogic } from './onboardingLogic'
import { ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingInstallStep } from './sdks/OnboardingInstallStep'
import { ErrorTrackingSDKInstructions } from './sdks/error-tracking/ErrorTrackingSDKInstructions'
import { ExperimentsSDKInstructions } from './sdks/experiments/ExperimentsSDKInstructions'
import { FeatureFlagsSDKInstructions } from './sdks/feature-flags/FeatureFlagsSDKInstructions'
import { LLMAnalyticsSDKInstructions } from './sdks/llm-analytics/LLMAnalyticsSDKInstructions'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'
import { SurveysSDKInstructions } from './sdks/surveys/SurveysSDKInstructions'
import { OnboardingWebAnalyticsAuthorizedDomainsStep } from './web-analytics/OnboardingWebAnalyticsAuthorizedDomainsStep'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Wrapper for custom onboarding content. This automatically includes billing, other products, and invite steps.
 */
const OnboardingWrapper = ({
    children,
    ...logicProps
}: { children: React.ReactNode } & OnboardingLogicProps): JSX.Element => {
    const logic = onboardingLogic(logicProps)
    const {
        productKey,
        currentOnboardingStep,
        shouldShowBillingStep,
        shouldShowReverseProxyStep,
        shouldShowDataWarehouseStep,
        product,
        waitForBilling,
    } = useValues(logic)
    const { setAllOnboardingSteps } = useActions(logic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const minAdminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    useEffect(() => {
        if (billingLoading && waitForBilling) {
            return
        }

        let steps: OnboardingStepElement[] = []
        if (Array.isArray(children)) {
            steps = [...children]
        } else {
            steps = [children as OnboardingStepElement]
        }

        if (shouldShowDataWarehouseStep) {
            const DataWarehouseStep = <OnboardingDataWarehouseSourcesStep />
            steps = [...steps, DataWarehouseStep]
        }

        if (shouldShowReverseProxyStep) {
            const ReverseProxyStep = <OnboardingReverseProxy />
            steps = [...steps, ReverseProxyStep]
        }

        const billingProduct = billing?.products.find((p) => p.type === productKey)
        if (shouldShowBillingStep && billingProduct) {
            const BillingStep = <OnboardingUpgradeStep product={billingProduct} />

            steps = [...steps, BillingStep]
        }

        const userCannotInvite = minAdminRestrictionReason && !currentOrganization?.members_can_invite
        if (!userCannotInvite) {
            const inviteTeammatesStep = <OnboardingInviteTeammates />
            steps = [...steps, inviteTeammatesStep]
        }

        setAllOnboardingSteps(steps.filter(Boolean))
    }, [children, billingLoading, waitForBilling, minAdminRestrictionReason, currentOrganization]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!product || !children) {
        return <></>
    }

    if (!currentOnboardingStep) {
        return (
            <div className="flex items-center justify-center my-20">
                <Spinner className="text-2xl text-secondary w-10 h-10" />
            </div>
        )
    }

    return currentOnboardingStep
}

const sessionReplayOnboardingToggle = (
    currentTeam: TeamType | TeamPublicType | null,
    selectedProducts: ProductKey[]
): ProductConfigOption => {
    const userDecision =
        currentTeam?.session_recording_opt_in ||
        selectedProducts.includes(ProductKey.SESSION_REPLAY) ||
        currentTeam?.product_intents?.some((intent) => intent.product_type === ProductKey.SESSION_REPLAY)

    return {
        title: 'Enable session recordings',
        description: `Turn on session recordings and watch how users experience your app. We will also turn on console log and network performance recording. You can change these settings any time in the settings panel.`,
        teamProperty: 'session_recording_opt_in',
        // TRICKY: if someone has shown secondary (or tertiary or...) product intent for replay we want to include it as enabled
        // particularly while we're not taking people through every product onboarding they showed interest in
        value: userDecision ?? false,
        type: 'toggle',
        visible: true,
    }
}
const ProductAnalyticsOnboarding = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { selectedProducts } = useValues(productSelectionLogic)

    // mount the logic here so that it stays mounted for the entire onboarding flow
    // not sure if there is a better way to do this
    useValues(newDashboardLogic)

    const options: ProductConfigOption[] = [
        {
            title: 'Autocapture frontend interactions',
            description: `If you use our JavaScript, React Native or iOS libraries, we'll automagically
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
        sessionReplayOnboardingToggle(currentTeam, selectedProducts),
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

    const filteredOptions = options.filter((option) => option.teamProperty !== 'session_recording_opt_in')

    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={ProductAnalyticsSDKInstructions} />
            <OnboardingProductConfiguration options={filteredOptions} />

            <OnboardingSessionReplayConfiguration />
        </OnboardingWrapper>
    )
}

const WebAnalyticsOnboarding = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { selectedProducts } = useValues(productSelectionLogic)

    const options: ProductConfigOption[] = [
        {
            title: 'Autocapture frontend interactions',
            description: `If you use our JavaScript, React Native or iOS libraries, we'll automagically
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
        sessionReplayOnboardingToggle(currentTeam, selectedProducts),
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
            <OnboardingInstallStep sdkInstructionMap={WebAnalyticsSDKInstructions} />
            <OnboardingWebAnalyticsAuthorizedDomainsStep />
            <OnboardingProductConfiguration options={options} />
        </OnboardingWrapper>
    )
}

const SessionReplayOnboarding = (): JSX.Element => {
    const { hasAvailableFeature } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)

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
        {
            type: 'select',
            title: 'Masking',
            description: 'Choose the level of masking for your recordings.',
            value: getMaskingLevelFromConfig(currentTeam?.session_recording_masking_config ?? {}),
            teamProperty: 'session_recording_masking_config',
            onChange: (value: string | number | null) => {
                return {
                    session_recording_masking_config: getMaskingConfigFromLevel(value as SessionRecordingMaskingLevel),
                }
            },
            selectOptions: [
                { value: 'total-privacy', label: 'Total privacy (mask all text/images)' },
                { value: 'normal', label: 'Normal (mask inputs but not text/images)' },
                { value: 'free-love', label: 'Free love (mask only passwords)' },
            ],
            visible: true,
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

    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={SessionReplaySDKInstructions} />
            <OnboardingProductConfiguration options={configOptions} />
        </OnboardingWrapper>
    )
}

const FeatureFlagsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={FeatureFlagsSDKInstructions} />
        </OnboardingWrapper>
    )
}

const ExperimentsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={ExperimentsSDKInstructions} />
        </OnboardingWrapper>
    )
}

const SurveysOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={SurveysSDKInstructions} />
        </OnboardingWrapper>
    )
}

const DataWarehouseOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <OnboardingDataWarehouseSourcesStep />
        </OnboardingWrapper>
    )
}

const ErrorTrackingOnboarding = (): JSX.Element => {
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <OnboardingWrapper
            onCompleteOnboarding={(productKey) => {
                if (productKey === ProductKey.ERROR_TRACKING) {
                    updateCurrentTeam({ autocapture_exceptions_opt_in: true })
                }
            }}
        >
            <OnboardingInstallStep sdkInstructionMap={ErrorTrackingSDKInstructions} />
            <OnboardingErrorTrackingSourceMapsStep />
            <OnboardingErrorTrackingAlertsStep />
        </OnboardingWrapper>
    )
}

const LLMAnalyticsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <OnboardingInstallStep sdkInstructionMap={LLMAnalyticsSDKInstructions} listeningForName="LLM generation" />
        </OnboardingWrapper>
    )
}

export const onboardingViews = {
    [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsOnboarding,
    [ProductKey.WEB_ANALYTICS]: WebAnalyticsOnboarding,
    [ProductKey.SESSION_REPLAY]: SessionReplayOnboarding,
    [ProductKey.FEATURE_FLAGS]: FeatureFlagsOnboarding,
    [ProductKey.EXPERIMENTS]: ExperimentsOnboarding,
    [ProductKey.SURVEYS]: SurveysOnboarding,
    [ProductKey.DATA_WAREHOUSE]: DataWarehouseOnboarding,
    [ProductKey.ERROR_TRACKING]: ErrorTrackingOnboarding,
    [ProductKey.LLM_ANALYTICS]: LLMAnalyticsOnboarding,
}

export function Onboarding(): JSX.Element | null {
    const { product, productKey } = useValues(onboardingLogic)

    // Show product selection when no product is selected
    if (!productKey) {
        return <ProductSelection />
    }

    if (!product) {
        return <></>
    }

    const OnboardingView = onboardingViews[productKey as keyof typeof onboardingViews]

    return (
        <div className="pt-4 pb-10">
            <OnboardingView />
        </div>
    )
}

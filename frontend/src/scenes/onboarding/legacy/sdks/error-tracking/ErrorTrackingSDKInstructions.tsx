import {
    APIInstallation,
    AndroidInstallation,
    AngularInstallation,
    ConvexErrorTrackingInstallation,
    DotNetInstallation,
    ElixirInstallation,
    FlutterInstallation,
    GoInstallation,
    IOSInstallation,
    HonoInstallation,
    JavaErrorTrackingInstallation,
    KMPErrorTrackingInstallation,
    WebInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    Nuxt36Installation,
    Nuxt37Installation,
    PHPInstallation,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RobloxInstallation,
    RubyInstallation,
    RubyOnRailsInstallation,
    RustInstallation,
    SvelteInstallation,
    UnityInstallation,
} from '@posthog/shared-onboarding/error-tracking'
import { PythonEventCapture } from '@posthog/shared-onboarding/product-analytics'

import { JS_WEB_SNIPPETS as BASE_JS_WEB_SNIPPETS } from 'scenes/onboarding/shared/jsWebSnippets'

import { SDKDocsLinkOverrides, SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'
import { ErrorTrackingWizardBanner } from './ErrorTrackingWizardBanner'

const JS_WEB_SNIPPETS = {
    ...BASE_JS_WEB_SNIPPETS,
}

const PYTHON_SNIPPETS = {
    PythonEventCapture,
}

export const ErrorTrackingSDKDocsLinkOverrides: SDKDocsLinkOverrides = {
    [SDKKey.CONVEX]: 'https://posthog.com/docs/libraries/convex',
}

const ErrorTrackingAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Angular',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'JavaScript Web',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Next.js',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    wizardIntegrationName: 'Node.js',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingNuxt37InstructionsWrapper = withOnboardingDocsWrapper({
    Installation: Nuxt37Installation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Nuxt 3.7+',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingNuxt36InstructionsWrapper = withOnboardingDocsWrapper({
    Installation: Nuxt36Installation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Nuxt 3.6 and below',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    snippets: PYTHON_SNIPPETS,
    wizardIntegrationName: 'Python',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'React',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Svelte',
    WizardBanner: ErrorTrackingWizardBanner,
})

const ErrorTrackingRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    wizardIntegrationName: 'Ruby',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingRubyOnRailsInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyOnRailsInstallation,
    wizardIntegrationName: 'Ruby on Rails',
    WizardBanner: ErrorTrackingWizardBanner,
})

const ErrorTrackingHonoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HonoInstallation,
    wizardIntegrationName: 'Hono',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    wizardIntegrationName: 'Android',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    wizardIntegrationName: 'Swift',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
})
const ErrorTrackingGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
})
const ErrorTrackingPHPInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PHPInstallation,
})
const ErrorTrackingElixirInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ElixirInstallation,
})
const ErrorTrackingDotNetInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DotNetInstallation,
})
const ErrorTrackingReactNativeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    wizardIntegrationName: 'React Native',
    WizardBanner: ErrorTrackingWizardBanner,
})
const ErrorTrackingAPIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: APIInstallation,
})
const ErrorTrackingRustInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RustInstallation,
})
const ErrorTrackingUnityInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: UnityInstallation,
})
const ErrorTrackingRobloxInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RobloxInstallation,
})
const ErrorTrackingJavaInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JavaErrorTrackingInstallation,
})
const ErrorTrackingKMPInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: KMPErrorTrackingInstallation,
})
const ErrorTrackingConvexInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ConvexErrorTrackingInstallation,
})
export const ErrorTrackingSDKInstructions: SDKInstructionsMap = {
    [SDKKey.ANGULAR]: ErrorTrackingAngularInstructionsWrapper,
    [SDKKey.JS_WEB]: ErrorTrackingWebInstructionsWrapper,
    [SDKKey.NEXT_JS]: ErrorTrackingNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: ErrorTrackingNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: ErrorTrackingNuxt37InstructionsWrapper,
    [SDKKey.NUXT_JS_36]: ErrorTrackingNuxt36InstructionsWrapper,
    [SDKKey.PYTHON]: ErrorTrackingPythonInstructionsWrapper,
    [SDKKey.REACT]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.SVELTE]: ErrorTrackingSvelteInstructionsWrapper,
    [SDKKey.TANSTACK_START]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.VITE]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.RUBY]: ErrorTrackingRubyInstructionsWrapper,
    [SDKKey.RUBY_ON_RAILS]: ErrorTrackingRubyOnRailsInstructionsWrapper,
    [SDKKey.HONO]: ErrorTrackingHonoInstructionsWrapper,
    [SDKKey.ANDROID]: ErrorTrackingAndroidInstructionsWrapper,
    [SDKKey.FLUTTER]: ErrorTrackingFlutterInstructionsWrapper,
    [SDKKey.GO]: ErrorTrackingGoInstructionsWrapper,
    [SDKKey.PHP]: ErrorTrackingPHPInstructionsWrapper,
    [SDKKey.ELIXIR]: ErrorTrackingElixirInstructionsWrapper,
    [SDKKey.DOTNET]: ErrorTrackingDotNetInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: ErrorTrackingReactNativeInstructionsWrapper,
    [SDKKey.IOS]: ErrorTrackingIOSInstructionsWrapper,
    [SDKKey.API]: ErrorTrackingAPIInstructionsWrapper,
    [SDKKey.RUST]: ErrorTrackingRustInstructionsWrapper,
    [SDKKey.UNITY]: ErrorTrackingUnityInstructionsWrapper,
    [SDKKey.ROBLOX]: ErrorTrackingRobloxInstructionsWrapper,
    [SDKKey.JAVA]: ErrorTrackingJavaInstructionsWrapper,
    [SDKKey.KMP]: ErrorTrackingKMPInstructionsWrapper,
    [SDKKey.CONVEX]: ErrorTrackingConvexInstructionsWrapper,
}

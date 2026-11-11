import {
    AndroidInstallation,
    FlutterInstallation,
    GoInstallation,
    IOSInstallation,
    JavaInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    OpenTelemetryInstallation,
    PythonInstallation,
    ReactNativeInstallation,
} from '@posthog/shared-onboarding/logs'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Logs uses standard OTel packages — the posthog-wizard doesn't support OTLP
// log setup, so wizardIntegrationName is intentionally omitted for all wrappers.

const LogsNodeJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
})

const LogsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
})

const LogsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
})

const LogsGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
})

const LogsJavaInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JavaInstallation,
})

const LogsOpenTelemetryInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenTelemetryInstallation,
})

const LogsIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
})

const LogsReactNativeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
})

const LogsAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
})

const LogsFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
})

export const LogsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.NODE_JS]: LogsNodeJSInstructionsWrapper,
    [SDKKey.NEXT_JS]: LogsNextJSInstructionsWrapper,
    [SDKKey.PYTHON]: LogsPythonInstructionsWrapper,
    [SDKKey.GO]: LogsGoInstructionsWrapper,
    [SDKKey.JAVA]: LogsJavaInstructionsWrapper,
    [SDKKey.OPENTELEMETRY]: LogsOpenTelemetryInstructionsWrapper,
    [SDKKey.IOS]: LogsIOSInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: LogsReactNativeInstructionsWrapper,
    [SDKKey.ANDROID]: LogsAndroidInstructionsWrapper,
    [SDKKey.FLUTTER]: LogsFlutterInstructionsWrapper,
}

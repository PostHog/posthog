import {
    GoInstallation,
    JavaInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    OpenTelemetryInstallation,
    PythonInstallation,
} from '@posthog/shared-onboarding/logs'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const LogsNodeJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    wizardIntegrationName: 'Node.js',
})

const LogsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    wizardIntegrationName: 'Next.js',
})

const LogsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    wizardIntegrationName: 'Python',
})

const LogsGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
    wizardIntegrationName: 'Go',
})

const LogsJavaInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JavaInstallation,
    wizardIntegrationName: 'Java',
})

const LogsOpenTelemetryInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenTelemetryInstallation,
    wizardIntegrationName: 'OpenTelemetry',
})

export const LogsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.NODE_JS]: LogsNodeJSInstructionsWrapper,
    [SDKKey.NEXT_JS]: LogsNextJSInstructionsWrapper,
    [SDKKey.PYTHON]: LogsPythonInstructionsWrapper,
    [SDKKey.GO]: LogsGoInstructionsWrapper,
    [SDKKey.JAVA]: LogsJavaInstructionsWrapper,
    [SDKKey.OPENTELEMETRY]: LogsOpenTelemetryInstructionsWrapper,
}

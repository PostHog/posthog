import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { WizardCommandBlock } from '../shared/wizard-sync/WizardCommandBlock'
import { PurpleWizardHog } from '../shared/wizardHog'
import { onboardingMcpStepLogic } from './onboardingMcpStepLogic'

export function OnboardingMcpStep(): JSX.Element {
    const { hasConnectedAgent } = useValues(onboardingMcpStepLogic)

    return (
        <OnboardingStep
            title="Connect your AI agent"
            subtitle="The PostHog MCP server lets agents like Claude Code, Cursor, and Codex read your PostHog data and set up features for you."
            stepKey={OnboardingStepKey.MCP}
            continueDisabledReason={
                hasConnectedAgent === false ? 'Connect your agent to PostHog to continue' : undefined
            }
            showSkip
        >
            <div className="max-w-xl mx-auto mt-6 space-y-6">
                <WizardCommandBlock
                    hog={PurpleWizardHog}
                    subcommand="mcp add"
                    description="Run this in your terminal. It asks which agents to connect, then signs your agent in to PostHog."
                />
                <div className="flex items-center justify-center gap-2" aria-live="polite">
                    {hasConnectedAgent ? (
                        <>
                            <IconCheckCircle className="text-success text-lg" />
                            <span className="font-semibold">Your agent is connected</span>
                        </>
                    ) : (
                        <>
                            <Spinner className="text-lg" />
                            <span className="text-secondary">Waiting for your agent to connect</span>
                        </>
                    )}
                </div>
            </div>
        </OnboardingStep>
    )
}

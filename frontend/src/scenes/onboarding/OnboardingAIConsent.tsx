import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { RobotHog } from 'lib/components/hedgehogs'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { OnboardingStepKey } from '~/types'

import { FlappyHog } from './FlappyHog'
import { OnboardingStep } from './OnboardingStep'

const EXAMPLE_PROMPTS = [
    'Show me recordings of users rage-clicking the paywall',
    'What does LTV mean?',
    'Build me a conversion funnel',
    'How many people actually use the dashboard?',
]

export const OnboardingAIConsent = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const isNotAdmin = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    // New accounts have `default=True` on the database, but older accounts may have null/false
    const isEnabledForOrganization = !!currentOrganization?.is_ai_data_processing_approved
    const [aiEnabled, setAiEnabled] = useState(isEnabledForOrganization)

    const [showFlappyHog, setShowFlappyHog] = useState(false)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 50, duration: 2000 })

    const handleContinue = (): void => {
        if (!isNotAdmin && aiEnabled !== currentOrganization?.is_ai_data_processing_approved) {
            updateOrganization({ is_ai_data_processing_approved: aiEnabled })
        }
    }

    return (
        <OnboardingStep
            stepKey={stepKey}
            title={isEnabledForOrganization ? 'PostHog AI is ready' : 'Activate PostHog AI'}
            onContinue={handleContinue}
        >
            <HogfettiComponent />
            <FlappyHog isOpen={showFlappyHog} onClose={() => setShowFlappyHog(false)} />

            <div className="mt-6">
                <div className="flex items-start gap-6 mb-8">
                    <div
                        className="hidden sm:block flex-shrink-0 w-32 cursor-pointer hover:scale-105 transition-transform"
                        onClick={() => setShowFlappyHog(true)}
                        title="Click me!"
                    >
                        <RobotHog className="w-full h-auto" />
                    </div>
                    <div className="flex-1">
                        <div className="flex items-center gap-2 mb-3">
                            <IconSparkles className="text-2xl text-warning" />
                            <span className="font-semibold text-lg">Your AI-powered product analyst</span>
                        </div>
                        <p className="text-muted mb-4">
                            <Link to="https://posthog.com/docs/posthog-ai" target="_blank" disableDocsPanel>
                                PostHog AI
                            </Link>{' '}
                            can answer product questions, build filters and queries, and won't judge you for asking
                            "what's a funnel?" for the third time.
                        </p>
                        <div>
                            <p className="text-muted text-sm mb-2">
                                Ask it things you'd be too embarrassed to ask a coworker:
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {EXAMPLE_PROMPTS.map((prompt) => (
                                    <div
                                        key={prompt}
                                        className="bg-bg-light border rounded-full px-3 py-1.5 text-sm italic"
                                    >
                                        "{prompt}"
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>

                <div className="border-2 border-accent-primary rounded-lg p-4 bg-accent-primary-highlight">
                    <div className="flex items-center justify-between gap-4">
                        <div>
                            <h4 className="font-semibold mb-1">
                                {isEnabledForOrganization ? 'PostHog AI is enabled' : 'Enable PostHog AI'}
                            </h4>
                            <p className="text-muted text-sm mb-0">
                                It's free to get started, and you can always set spend limits anytime. PostHog AI uses
                                third-party LLM providers (OpenAI and Anthropic). Your data will not be used for
                                training models.{' '}
                                <Link to="https://posthog.com/docs/posthog-ai/faq" target="_blank" disableDocsPanel>
                                    Learn more
                                </Link>
                            </p>
                        </div>
                        <LemonSwitch
                            checked={aiEnabled}
                            onChange={(checked) => {
                                setAiEnabled(checked)
                                if (checked) {
                                    triggerHogfetti()
                                }
                            }}
                            disabled={!!isNotAdmin || currentOrganizationLoading}
                            data-attr="onboarding-ai-consent-toggle"
                        />
                    </div>
                    {isNotAdmin && (
                        <p className="text-warning text-sm mt-2 mb-0">
                            Only organization admins can manage AI features. Ask an admin to change this setting.
                        </p>
                    )}
                </div>
            </div>
        </OnboardingStep>
    )
}

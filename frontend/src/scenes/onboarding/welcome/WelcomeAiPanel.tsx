import { useActions, useValues } from 'kea'

import * as robotPng from '@posthog/brand/hoggies/png/robot'
import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'

const HedgehogRobot = pngHoggie(robotPng)

const SUGGESTIONS = [
    'Find where people drop off in my signup flow',
    'See how people use a feature I just shipped',
    'Learn which pages bring in the most signups',
]

export function WelcomeAiPanel(): JSX.Element {
    const { aiPrompt } = useValues(onboardingWelcomeLogic)
    const { setAiPrompt, submitAiPrompt } = useActions(onboardingWelcomeLogic)

    return (
        <div className="mx-auto flex max-w-xl flex-col items-center gap-4 py-8 text-center">
            <HedgehogRobot className="w-28" />
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-xl font-semibold">Tell PostHog AI what you want to do</h2>
                <p className="m-0 text-secondary">
                    Describe what you're building or what you want to learn. PostHog AI picks the right tools and gets
                    you started.
                </p>
            </div>
            <LemonTextArea
                className="w-full text-left"
                value={aiPrompt}
                onChange={setAiPrompt}
                onPressCmdEnter={(value) => submitAiPrompt(value)}
                placeholder="For example: I want to know why people cancel their subscription"
                minRows={3}
                data-attr="onboarding-welcome-ai-prompt"
            />
            <LemonButton
                type="primary"
                icon={<IconSparkles />}
                onClick={() => submitAiPrompt(aiPrompt)}
                disabledReason={aiPrompt.trim() ? undefined : 'Describe what you want to do first'}
                data-attr="onboarding-welcome-ai-submit"
            >
                Start a conversation
            </LemonButton>
            <div className="flex flex-col items-center gap-2">
                <span className="text-xs text-secondary">Or start from an example</span>
                <div className="flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((suggestion) => (
                        <LemonButton
                            key={suggestion}
                            type="secondary"
                            size="small"
                            onClick={() => submitAiPrompt(suggestion, true)}
                            data-attr="onboarding-welcome-ai-suggestion"
                        >
                            {suggestion}
                        </LemonButton>
                    ))}
                </div>
            </div>
        </div>
    )
}

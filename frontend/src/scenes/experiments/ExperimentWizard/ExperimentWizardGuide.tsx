import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLightBulb, IconSparkles } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { ExperimentWizardStep, experimentWizardLogic } from './experimentWizardLogic'

interface GuideContent {
    title: string
    tips: string[]
}

const GUIDE_CONTENT: Record<ExperimentWizardStep, GuideContent> = {
    about: {
        title: 'Feature flags',
        tips: [
            'Feature flags are placed in your codebase to switch between variants. We will give you a code snippet at the end of the wizard.',
            'Feature flags also control the rollout process, which you can configure in the next step.',
            'In most cases you will want a new feature flag for this experiment. If you however want to use an existing one, the rollout configuration can only be modified on the feature flag directly.',
        ],
    },
    variants: {
        title: 'Variants',
        tips: [
            "A variant is one version of what you're testing, like your current page (control) and the change you want to try (test).",
            'The more variants you add, the more traffic you need to get reliable results.',
            'It is recommended to split traffic equally between variants. The lower the traffic a variant has, the longer it will take to reach reliable results.',
        ],
    },
    analytics: {
        title: 'Measuring impact',
        tips: [
            'By default every user exposed to the experiment is included in the analysis.',
            'You can customize it to narrow it down further, but be careful not to introduce bias.',
            'You can change inclusion criteria and metrics afterwards. This impacts only the analysis, not what your user sees or data collection.',
        ],
    },
}

export function ExperimentWizardGuide(): JSX.Element {
    const { currentStep } = useValues(experimentWizardLogic)
    const { reportExperimentWizardAskAiClicked } = useActions(eventUsageLogic)

    const { openMax } = useMaxTool({
        identifier: 'create_experiment',
        initialMaxPrompt: 'Create an experiment for ',
        callback: (toolOutput: { experiment_id?: string | number; error?: string }) => {
            if (toolOutput?.error || !toolOutput?.experiment_id) {
                lemonToast.error(`Failed to create experiment: ${toolOutput?.error || 'Unknown error'}`)
                return
            }
            router.actions.push(urls.experiment(toolOutput.experiment_id))
        },
        // Recorded as `ai_entry_point` on `experiment created`, to attribute AI-created experiments to this button
        context: { entry_point: 'experiment_wizard_guide' },
    })

    const guide = GUIDE_CONTENT[currentStep]

    return (
        <div className="sticky top-6 rounded-lg border border-dashed border-primary bg-bg-light p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <IconLightBulb className="size-4 shrink-0" />
                <h4 className="m-0 text-sm font-semibold">{guide.title}</h4>
            </div>

            <ul className="m-0 pl-5 list-disc text-xs text-muted leading-relaxed space-y-1.5">
                {guide.tips.map((tip, i) => (
                    <li key={i}>{tip}</li>
                ))}
            </ul>

            {openMax && (
                <div className="flex flex-col gap-2 pt-3 border-t border-dashed border-primary">
                    <div className="text-sm text-default">Rather describe it? PostHog AI can set it up for you.</div>
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconSparkles className="text-ai" />}
                            onClick={() => {
                                reportExperimentWizardAskAiClicked(currentStep)
                                openMax()
                            }}
                            data-attr="experiment-wizard-guide-ask-ai"
                        >
                            {/* Skip the animation in Storybook so visual snapshots don't flake on the moving gradient */}
                            <span
                                className={cn(
                                    'rainbow-text font-semibold',
                                    !(inStorybook() || inStorybookTestRunner()) && 'rainbow-text-animating'
                                )}
                            >
                                Ask AI
                            </span>
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

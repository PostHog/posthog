import { useActions, useValues } from 'kea'

import { IconLightBulb, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
            'In most cases you will want a new feature flag for this experiment. If you however want to use an existing one, keep in mind that changing the rollout configuration will modify the feature flag directly.',
        ],
    },
    variants: {
        title: 'Configuring variants',
        tips: [
            'Start with a simple A/B test (control vs. one variant). The more variants you add, the more traffic you need to get reliable results.',
            'Variants by default have an equal split of traffic. If you adjust it, please consider the implication on the measurements.',
        ],
    },
    analytics: {
        title: 'Measuring impact',
        tips: [
            'By default every user exposed to the experiment is included in the analysis.',
            'You can customize it to narrow it down further, but be careful not to introduce a bias.',
            'You can change inclusion criteria and metrics afterwards, it is just used for evaluation, events are always gathered.',
        ],
    },
}

export function ExperimentWizardGuide(): JSX.Element {
    const { currentStep } = useValues(experimentWizardLogic)
    const { toggleGuide } = useActions(experimentWizardLogic)

    const guide = GUIDE_CONTENT[currentStep]

    return (
        <div className="sticky top-6 space-y-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-sm font-medium text-secondary">
                    <IconLightBulb className="size-4" />
                    Guide
                </div>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconX />}
                    onClick={toggleGuide}
                    tooltip="Hide guide"
                />
            </div>

            <h4 className="text-sm font-semibold">{guide.title}</h4>

            <ul className="space-y-2.5">
                {guide.tips.map((tip, i) => (
                    <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-secondary">
                        <span className="text-muted select-none shrink-0">&#8226;</span>
                        <span>{tip}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}

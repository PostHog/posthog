import { Link } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { OnboardingStepComponentType } from './onboardingLogic'

export const OnboardingWorkflowsSetup: OnboardingStepComponentType = () => {
    return (
        <OnboardingStep
            stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
            title="Set up workflows"
            continueText="Go to workflows"
        >
            <div className="mt-6 space-y-4 text-secondary">
                <p>
                    Build automated workflows to notify users and trigger actions across your stack. We&apos;ll guide
                    you through creating a trigger, adding an action, and launching your first workflow.
                </p>
                <p>
                    Need help getting started? Check the{' '}
                    <Link to="https://posthog.com/docs/workflows/start-here" target="_blank">
                        Workflows docs
                    </Link>
                    .
                </p>
            </div>
        </OnboardingStep>
    )
}

OnboardingWorkflowsSetup.stepKey = OnboardingStepKey.PRODUCT_CONFIGURATION

import { Link } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { WorkflowTemplateChooser } from 'products/workflows/frontend/Workflows/templates/WorkflowTemplateChooser'

import { OnboardingStep } from './OnboardingStep'
import { OnboardingStepComponentType } from './onboardingLogic'

export const OnboardingWorkflowsSetup: OnboardingStepComponentType = () => {
    return (
        <OnboardingStep
            stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
            title="Set up workflows"
            continueText="Go to workflows"
        >
            <div className="flex flex-col gap-2 text-secondary">
                <p className="m-0">
                    Build automated workflows to notify users and trigger actions across your stack. Below are some
                    popular workflow templates to get you started:
                </p>

                <WorkflowTemplateChooser />

                <p className="mt-4">
                    Want to learn more about workflows? Check the{' '}
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

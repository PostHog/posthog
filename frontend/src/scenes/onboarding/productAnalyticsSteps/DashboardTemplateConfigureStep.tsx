import { DashboardTemplateVariables } from 'scenes/dashboard/DashboardTemplateVariables'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    return (
        <OnboardingStep title="Configure your template" stepKey={stepKey}>
            <p>Select the events or website elements that represent important parts of your funnel.</p>
            <DashboardTemplateVariables />
        </OnboardingStep>
    )
}

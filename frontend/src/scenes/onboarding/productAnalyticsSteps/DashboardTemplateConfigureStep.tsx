import { useValues } from 'kea'
import { DashboardTemplateVariables } from 'scenes/dashboard/DashboardTemplateVariables'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { activeDashboardTemplate } = useValues(onboardingTemplateConfigLogic)

    return (
        <OnboardingStep
            title={activeDashboardTemplate?.template_name || 'Configure dashboard'}
            stepKey={stepKey}
            breadcrumbHighlightName={OnboardingStepKey.DASHBOARD_TEMPLATE}
        >
            <p>Select the events or website elements that represent important parts of your funnel.</p>
            <DashboardTemplateVariables />
        </OnboardingStep>
    )
}

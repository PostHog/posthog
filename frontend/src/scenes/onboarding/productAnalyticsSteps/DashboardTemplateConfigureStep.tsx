import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { DashboardTemplateVariables } from 'scenes/dashboard/DashboardTemplateVariables'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { activeDashboardTemplate } = useValues(onboardingTemplateConfigLogic)
    const { createDashboardFromTemplate } = useActions(newDashboardLogic)
    const { isLoading } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)

    const [isSubmitting, setIsSubmitting] = useState(false)

    return (
        <OnboardingStep
            title={activeDashboardTemplate?.template_name || 'Configure dashboard'}
            stepKey={stepKey}
            breadcrumbHighlightName={OnboardingStepKey.DASHBOARD_TEMPLATE}
            continueOverride={
                <LemonButton
                    type="primary"
                    onClick={() => {
                        if (activeDashboardTemplate) {
                            setIsSubmitting(true)
                            createDashboardFromTemplate(activeDashboardTemplate, variables, false)
                        }
                    }}
                    loading={isLoading}
                >
                    Create dashboard
                </LemonButton>
            }
        >
            {isSubmitting || isLoading ? (
                <p>Creating dashboard...</p>
            ) : (
                <>
                    <p>Select the events or website elements that represent important parts of your funnel.</p>
                    <DashboardTemplateVariables />
                </>
            )}
        </OnboardingStep>
    )
}

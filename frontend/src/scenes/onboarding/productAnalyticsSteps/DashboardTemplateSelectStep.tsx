import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useEffect } from 'react'
import { DashboardTemplateChooser } from 'scenes/dashboard/DashboardTemplateChooser'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { OnboardingStepKey, TemplateAvailabilityContext } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

export const OnboardingDashboardTemplateSelectStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { goToNextStep } = useActions(onboardingLogic)
    const { clearActiveDashboardTemplate } = useActions(newDashboardLogic)
    const {
        setDashboardCreatedDuringOnboarding,
        reportTemplateSelected,
        showTemplateRequestModal,
        hideTemplateRequestModal,
    } = useActions(onboardingTemplateConfigLogic)
    const { isTemplateRequestModalOpen, isTemplateRequestFormSubmitting } = useValues(onboardingTemplateConfigLogic)

    // TODO: this is hacky, find a better way to clear the active template when coming back to this screen
    useEffect(() => {
        clearActiveDashboardTemplate()
    }, [])

    return (
        <OnboardingStep
            title="Start with a dashboard template"
            stepKey={stepKey}
            continueOverride={
                <div className="flex justify-end gap-x-2">
                    <LemonButton
                        type="secondary"
                        status="alt"
                        onClick={() => {
                            showTemplateRequestModal()
                        }}
                        data-attr="onboarding-skip-button"
                    >
                        I need a different template
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            goToNextStep(2)
                        }}
                        data-attr="onboarding-skip-button"
                    >
                        Skip for now
                    </LemonButton>
                </div>
            }
        >
            <p>
                Get useful insights from your events super fast with our dashboard templates. Select one to get started
                with based on your market and industry.
            </p>
            <DashboardTemplateChooser
                onItemClick={(template) => {
                    // clear the saved dashboard so we don't skip the next step
                    setDashboardCreatedDuringOnboarding(null)
                    reportTemplateSelected(template)
                    if (template.variables?.length && template.variables.length > 0) {
                        goToNextStep()
                    }
                }}
                redirectAfterCreation={false}
                availabilityContexts={[TemplateAvailabilityContext.ONBOARDING]}
            />
            <LemonModal
                title="What kind of template do you need?"
                isOpen={isTemplateRequestModalOpen}
                onClose={hideTemplateRequestModal}
            >
                <div className="max-w-md">
                    <p>
                        PostHog can collect and visualize data from anywhere. We're still adding more templates to this
                        onboarding flow for different use-cases and business types.
                    </p>
                    <p>Let us know what kind of template you'd like to see and we'll work on adding one.</p>
                    <Form
                        logic={onboardingTemplateConfigLogic}
                        formKey="templateRequestForm"
                        className="my-4 gap-y-4"
                        enableFormOnSubmit
                    >
                        <LemonField name="templateRequest" className="mb-4">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus
                                data-attr="templateRequestForm"
                                type="text"
                                disabled={isTemplateRequestFormSubmitting}
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={isTemplateRequestFormSubmitting ? 'Submitting...' : undefined}
                        >
                            Continue
                        </LemonButton>
                    </Form>
                </div>
            </LemonModal>
        </OnboardingStep>
    )
}

import { GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { PartnerReviewApi } from '~/generated/core/api.schemas'

import { reviewProgress } from '../oauthAppProvisioningStatus'

export function OAuthAppReviewProgress({ review }: { review: PartnerReviewApi }): JSX.Element {
    const { steps, currentStep } = reviewProgress(review)

    return (
        <GuidedWizardStepper
            steps={steps}
            currentStep={currentStep}
            unlistedStepPosition="end"
            className="flex-wrap -ml-2"
            aria-label="Review progress"
        />
    )
}

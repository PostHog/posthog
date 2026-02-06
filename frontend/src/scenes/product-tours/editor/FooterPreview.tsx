import { useValues } from 'kea'

import { productTourLogic } from '../productTourLogic'
import { isBannerAnnouncement } from '../productToursLogic'
import { hasElementTarget } from '../stepUtils'
import { PostHogLogo } from './icons'

export function FooterPreview({ tourId }: { tourId: string }): JSX.Element | null {
    const { productTour, productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))

    const steps = productTourForm.content?.steps ?? []
    const step = steps[selectedStepIndex]
    const appearance = productTourForm.content?.appearance

    if (productTour && isBannerAnnouncement(productTour)) {
        return null
    }

    if (!step) {
        return null
    }

    const totalSteps = steps.length
    const isFirstStep = selectedStepIndex === 0

    const hasCustomButtons = !!step.buttons
    const needsDefaultButtons = step.progressionTrigger === 'button' || !hasElementTarget(step)
    const showButtons = hasCustomButtons || needsDefaultButtons

    const showProgress = totalSteps > 1

    const showBranding = isFirstStep && !appearance?.whiteLabel

    if (!showButtons && !showProgress && !showBranding) {
        return null
    }

    const isLastStep = selectedStepIndex >= totalSteps - 1
    const primaryText = step.buttons?.primary?.text ?? (isLastStep ? 'Done' : 'Next')
    const secondaryText = step.buttons?.secondary?.text ?? 'Back'
    const showSecondary = hasCustomButtons ? !!step.buttons?.secondary : !isFirstStep

    return (
        <>
            {(showButtons || showProgress) && (
                <div className="StepContentEditor__footer">
                    {showProgress && (
                        <span className="StepContentEditor__progress">
                            {selectedStepIndex + 1} of {totalSteps}
                        </span>
                    )}
                    {showButtons && (
                        <div className="StepContentEditor__buttons">
                            {showSecondary && (
                                <button
                                    type="button"
                                    className="StepContentEditor__button StepContentEditor__button--secondary"
                                >
                                    {secondaryText}
                                </button>
                            )}
                            <button
                                type="button"
                                className="StepContentEditor__button StepContentEditor__button--primary"
                            >
                                {primaryText}
                            </button>
                        </div>
                    )}
                </div>
            )}
            {showBranding && (
                <div className="StepContentEditor__branding">
                    Tour by <PostHogLogo />
                </div>
            )}
        </>
    )
}

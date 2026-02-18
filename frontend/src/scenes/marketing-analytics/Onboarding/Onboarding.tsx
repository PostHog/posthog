import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { ConversionGoalsConfiguration } from '../../web-analytics/tabs/marketing-analytics/frontend/components/settings/ConversionGoalsConfiguration'
import { marketingAnalyticsLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import { AddSourceStep } from './AddSourceStep'
import { MarketingWizardStepper } from './MarketingWizardStepper'
import { MarketingOnboardingStep, marketingOnboardingLogic } from './marketingOnboardingLogic'

interface OnboardingProps {
    completeOnboarding: () => void
}

export function Onboarding({ completeOnboarding }: OnboardingProps): JSX.Element {
    const { reportMarketingAnalyticsOnboardingViewed, reportMarketingAnalyticsOnboardingCompleted } =
        useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { hasSources } = useValues(marketingAnalyticsLogic)
    const { currentStep } = useValues(marketingOnboardingLogic)
    const { setStep, goToNextStep } = useActions(marketingOnboardingLogic)

    // If user has sources and is on welcome, skip to add-source
    useEffect(() => {
        if (hasSources && currentStep === 'welcome') {
            setStep('add-source')
        }
    }, [hasSources, currentStep, setStep])

    useOnMountEffect(() => {
        reportMarketingAnalyticsOnboardingViewed()
    })

    const handleComplete = (): void => {
        reportMarketingAnalyticsOnboardingCompleted(hasSources)
        addProductIntent({
            product_type: ProductKey.MARKETING_ANALYTICS,
            intent_context: ProductIntentContext.MARKETING_ANALYTICS_ONBOARDING_COMPLETED,
            metadata: { has_sources: hasSources },
        })
        completeOnboarding()
    }

    const handleStepClick = (step: MarketingOnboardingStep): void => {
        if (step === 'done') {
            handleComplete()
        } else {
            setStep(step)
        }
    }

    const handleNextStep = (): void => {
        if (currentStep === 'conversion-goals') {
            handleComplete()
        } else {
            goToNextStep()
        }
    }

    return (
        <div className="space-y-6">
            <MarketingWizardStepper currentStep={currentStep} onStepClick={handleStepClick} />

            {currentStep === 'welcome' && <WelcomeStep onContinue={() => setStep('add-source')} />}

            {currentStep === 'add-source' && <AddSourceStep onContinue={handleNextStep} hasSources={hasSources} />}

            {currentStep === 'conversion-goals' && (
                <ConversionGoalsStep onContinue={handleComplete} onSkip={handleComplete} />
            )}
        </div>
    )
}

function WelcomeStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    return (
        <ProductIntroduction
            productName="Marketing analytics"
            productKey={ProductKey.MARKETING_ANALYTICS}
            thingName="marketing integration"
            titleOverride="Welcome to Marketing analytics"
            description="Track your marketing campaigns performance across all your ad platforms. Connect your data sources to see spend, conversions, and ROI in one place."
            action={onContinue}
            actionElementOverride={
                <LemonButton type="primary" onClick={onContinue} sideIcon={<IconArrowRight />}>
                    Get started
                </LemonButton>
            }
            isEmpty={true}
            docsURL="https://posthog.com/docs/web-analytics/marketing-analytics"
            customHog={FilmCameraHog}
        />
    )
}

function ConversionGoalsStep({ onContinue, onSkip }: { onContinue: () => void; onSkip: () => void }): JSX.Element {
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const hasConversionGoals = conversion_goals.length > 0

    return (
        <LemonCard hoverEffect={false}>
            <div className="space-y-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Configure conversion goals</h3>
                    <p className="text-sm text-muted-alt">
                        Define what actions count as conversions to measure your campaign effectiveness.
                    </p>
                </div>

                <ConversionGoalsConfiguration hideTitle hideDescription />

                <div className="flex justify-end gap-2 pt-4 border-t border-primary">
                    {!hasConversionGoals && (
                        <LemonButton type="secondary" onClick={onSkip}>
                            I'll configure later
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={onContinue}
                        sideIcon={<IconArrowRight />}
                        disabledReason={!hasConversionGoals ? 'Add at least one conversion goal' : undefined}
                    >
                        Continue
                    </LemonButton>
                </div>

                <div className="text-center">
                    <p className="text-xs text-muted-alt">
                        You can always configure conversion goals later in{' '}
                        <Link to="/settings/environment-marketing-analytics">settings</Link>
                    </p>
                </div>
            </div>
        </LemonCard>
    )
}

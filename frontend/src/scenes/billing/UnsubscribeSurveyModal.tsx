import './UnsubscribeSurveyModal.scss'

import { useActions, useValues } from 'kea'
import { SurveyEventProperties } from 'posthog-js'
import { useState } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonLabel,
    LemonModal,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { HeartHog } from 'lib/components/hedgehogs'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { AddonFeatureLossNotice } from './AddonFeatureLossNotice'
import { billingLogic } from './billingLogic'
import {
    UNSUBSCRIBE_REASONS,
    billingProductLogic,
    isPlatformAndSupportAddon,
    randomizeReasons,
} from './billingProductLogic'

export const UnsubscribeSurveyModal = ({
    product,
}: {
    product: BillingProductV2Type | BillingProductV2AddonType
}): JSX.Element | null => {
    const { trigger, HogfettiComponent } = useHogfetti()

    const { surveyID, surveyResponse, isAddonProduct, unsubscribeModalStep, unsubscribeReasonQuestions } = useValues(
        billingProductLogic({ product, hogfettiTrigger: trigger })
    )
    const {
        setSurveyResponse,
        toggleSurveyReason,
        reportSurveyDismissed,
        setUnsubscribeModalStep,
        resetUnsubscribeModalStep,
        setHedgehogSatisfied,
        triggerMoreHedgehogs,
    } = useActions(billingProductLogic({ product }))
    const { deactivateProduct, resetUnsubscribeError } = useActions(billingLogic)
    const { unsubscribeError, billingLoading, billing } = useValues(billingLogic)
    const { openSupportForm } = useActions(supportLogic)
    const [randomizedReasons] = useState(
        process?.env.STORYBOOK ? UNSUBSCRIBE_REASONS : randomizeReasons(UNSUBSCRIBE_REASONS)
    )

    const textAreaNotEmpty = surveyResponse[SurveyEventProperties.SURVEY_RESPONSE]?.length > 0

    let action = 'Unsubscribe'
    let actionVerb = 'unsubscribing'
    if (billing?.subscription_level === 'paid') {
        action = isAddonProduct ? 'Remove addon' : 'Downgrade'
        actionVerb = isAddonProduct ? 'removing this addon' : 'downgrading'
    }

    const handleUnsubscribe = (): void => {
        if (surveyResponse['$survey_response_2'].includes('Not enough hedgehogs')) {
            setUnsubscribeModalStep(2)
            triggerMoreHedgehogs()
        } else {
            deactivateProduct(billing?.subscription_level === 'paid' && !isAddonProduct ? 'all_products' : product.type)
        }
    }

    const renderHedgehogStep = (): JSX.Element => (
        <div className="flex flex-col gap-4">
            <div className="text-center">
                <h3 className="text-lg mb-2">How about now? Was that enough hedgehogs?</h3>
                <p className="text-secondary mb-4">Look at all these adorable hedgehogs dancing just for you! 🦔✨</p>
                <div className="flex justify-center items-center">
                    <HeartHog width="100" height="100" />
                </div>
            </div>
            <div className="flex gap-2 justify-center">
                <Link onClick={triggerMoreHedgehogs} disabled={billingLoading}>
                    Still not enough! More hedgehogs! 🦔
                </Link>
            </div>
            <LemonDivider />
            <div className="deprecated-space-y-2 flex flex-col items-center justify-center">
                <LemonButton
                    type="primary"
                    loading={billingLoading}
                    onClick={() => {
                        setHedgehogSatisfied(true)
                        deactivateProduct(
                            billing?.subscription_level === 'paid' && !isAddonProduct ? 'all_products' : product.type
                        )
                    }}
                >
                    Never enough, proceed with {action}
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    disabled={billingLoading}
                    onClick={() => {
                        resetUnsubscribeModalStep()
                        reportSurveyDismissed(surveyID)
                    }}
                >
                    You convinced me to stay! 💕
                </LemonButton>
            </div>
        </div>
    )

    return (
        <>
            <HogfettiComponent />
            <LemonModal
                onClose={() => {
                    reportSurveyDismissed(surveyID)
                    resetUnsubscribeError()
                    resetUnsubscribeModalStep()
                }}
                width="max(44vw)"
                title={
                    isAddonProduct
                        ? action
                        : product.type === 'platform_and_support'
                          ? `${action} your plan`
                          : `${action} from ${product.name}`
                }
                footer={
                    unsubscribeModalStep === 1 ? (
                        <>
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    reportSurveyDismissed(surveyID)
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type={textAreaNotEmpty ? 'primary' : 'secondary'}
                                disabledReason={
                                    surveyResponse['$survey_response_2'].length === 0
                                        ? 'Please select a reason'
                                        : !textAreaNotEmpty
                                          ? 'Please share your feedback'
                                          : undefined
                                }
                                onClick={handleUnsubscribe}
                                loading={billingLoading}
                            >
                                {action}
                            </LemonButton>
                        </>
                    ) : null
                }
            >
                {unsubscribeModalStep === 1 ? (
                    <div className="flex flex-col gap-3.5">
                        {unsubscribeError && (
                            <LemonBanner type="error">
                                <p>
                                    {unsubscribeError.detail} {unsubscribeError.link}
                                </p>
                            </LemonBanner>
                        )}
                        {isAddonProduct ? (
                            <p className="mb-0">
                                We're sorry to see you go! Please note, you'll lose access to the addon features
                                immediately.
                            </p>
                        ) : (
                            <p className="mb-0">
                                We're sorry to see you go! Please note, you'll lose access to platform features and
                                usage limits will apply immediately. And if you have any outstanding invoices, they will
                                be billed immediately.{' '}
                                <Link to={billing?.stripe_portal_url} target="_blank">
                                    View invoices
                                </Link>
                            </p>
                        )}

                        {isPlatformAndSupportAddon(product) && <AddonFeatureLossNotice product={product} />}

                        <LemonLabel>
                            {billing?.subscription_level === 'paid'
                                ? `Why are you ${actionVerb}?`
                                : `Why are you ${actionVerb} from ${product.name}?`}{' '}
                            <i className="text-secondary">(you can select multiple)</i>
                            <Tooltip title="Required">
                                <span className="text-danger">*</span>
                            </Tooltip>
                        </LemonLabel>
                        <div className="grid grid-cols-2 gap-2">
                            {randomizedReasons.map((reason) => (
                                <LemonCheckbox
                                    bordered
                                    key={reason.reason}
                                    label={reason.reason}
                                    data-attr={`unsubscribe-reason-${reason.reason.toLowerCase().replace(' ', '-')}`}
                                    checked={surveyResponse['$survey_response_2'].includes(reason.reason)}
                                    onChange={() => toggleSurveyReason(reason.reason)}
                                    className="w-full"
                                    labelClassName="w-full"
                                />
                            ))}
                        </div>

                        {surveyResponse['$survey_response_2'].length > 0 && (
                            <LemonTextArea
                                data-attr="unsubscribe-reason-survey-textarea"
                                placeholder={unsubscribeReasonQuestions}
                                value={surveyResponse[SurveyEventProperties.SURVEY_RESPONSE]}
                                onChange={(value) => {
                                    setSurveyResponse(SurveyEventProperties.SURVEY_RESPONSE, value)
                                }}
                            />
                        )}

                        <LemonBanner type="info">
                            <p>
                                {'Are you looking to control your costs? Learn about ways to '}
                                <Link
                                    to="https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs"
                                    target="_blank"
                                    onClick={() => {
                                        reportSurveyDismissed(surveyID)
                                    }}
                                >
                                    reduce your bill
                                </Link>
                                {`${product.type !== 'session_replay' ? ' or ' : ', '}`}
                                <Link
                                    to=""
                                    target="_blank"
                                    onClick={() => {
                                        reportSurveyDismissed(surveyID)
                                        openSupportForm({ target_area: 'billing', isEmailFormOpen: true })
                                    }}
                                >
                                    chat with support
                                </Link>
                                {product.type === 'session_replay' && (
                                    <>
                                        {', or '}
                                        <Link
                                            to="mailto:sales@posthog.com?subject=Joining%session%replay%controls%20beta"
                                            target="_blank"
                                            onClick={() => {
                                                reportSurveyDismissed(surveyID)
                                            }}
                                        >
                                            join our beta
                                        </Link>
                                        {' for tuning recording volume with sampling and minimum duration.'}
                                    </>
                                )}
                                .
                            </p>
                        </LemonBanner>
                    </div>
                ) : (
                    renderHedgehogStep()
                )}
            </LemonModal>
        </>
    )
}

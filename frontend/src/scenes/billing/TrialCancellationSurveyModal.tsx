import { useActions, useValues } from 'kea'
import { SurveyEventProperties } from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonLabel, LemonModal, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { AddonFeatureLossNotice } from './AddonFeatureLossNotice'
import {
    TRIAL_CANCEL_REASONS,
    billingProductLogic,
    isPlatformAndSupportAddon,
    randomizeReasons,
} from './billingProductLogic'

export const TrialCancellationSurveyModal = ({
    product,
}: {
    product: BillingProductV2Type | BillingProductV2AddonType
}): JSX.Element | null => {
    const { surveyID, surveyResponse, trialCancelReasonQuestions, trialLoading } = useValues(
        billingProductLogic({ product })
    )
    const { setSurveyResponse, toggleSurveyReason, reportSurveyDismissed, cancelTrial } = useActions(
        billingProductLogic({ product })
    )
    const [randomizedReasons] = useState(() => randomizeReasons(TRIAL_CANCEL_REASONS))

    const action = 'Cancel trial'
    const actionVerb = 'cancelling the trial'

    const handleTrialCancel = (): void => {
        cancelTrial()
    }

    return (
        <LemonModal
            onClose={() => {
                reportSurveyDismissed(surveyID)
            }}
            width="max(44vw)"
            title={`${action} for ${product.name}`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            reportSurveyDismissed(surveyID)
                        }}
                    >
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            surveyResponse['$survey_response_2'].length === 0 ? 'Please select a reason' : undefined
                        }
                        onClick={handleTrialCancel}
                        loading={trialLoading}
                    >
                        {action}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3.5">
                {isPlatformAndSupportAddon(product) && <AddonFeatureLossNotice product={product} />}

                <LemonLabel>
                    Why are you {actionVerb}? <i className="text-secondary">(you can select multiple)</i>
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
                            data-attr={`trial-cancel-reason-${reason.reason.toLowerCase().replace(/ /g, '-')}`}
                            checked={surveyResponse['$survey_response_2'].includes(reason.reason)}
                            onChange={() => toggleSurveyReason(reason.reason)}
                            className="w-full"
                            labelClassName="w-full"
                        />
                    ))}
                </div>
                {surveyResponse.$survey_response_2.length > 0 && (
                    <LemonTextArea
                        data-attr="trial-cancel-reason-survey-textarea"
                        placeholder={trialCancelReasonQuestions}
                        value={surveyResponse[SurveyEventProperties.SURVEY_RESPONSE]}
                        onChange={(value) => {
                            setSurveyResponse(SurveyEventProperties.SURVEY_RESPONSE, value)
                        }}
                    />
                )}
            </div>
        </LemonModal>
    )
}

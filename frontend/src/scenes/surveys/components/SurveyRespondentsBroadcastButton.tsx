import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'
import { MessageAudienceShown } from 'products/workflows/frontend/MessageAudience/MessageAudienceShown'

import { SURVEY_RESPONDENTS_SOURCE, surveyRespondentsBroadcastLogic } from './surveyRespondentsBroadcastLogic'

export function SurveyRespondentsBroadcastButton({ surveyId }: { surveyId: string }): JSX.Element {
    const logic = surveyRespondentsBroadcastLogic({ surveyId })
    const { respondentsCohortLoading, hasActiveFilters } = useValues(logic)
    const { emailRespondents } = useActions(logic)
    const accessDisabledReason = messageAudienceAccessDisabledReason()
    return (
        <>
            {!accessDisabledReason && (
                <MessageAudienceShown source={SURVEY_RESPONDENTS_SOURCE} destination="broadcast" />
            )}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSend />}
                onClick={emailRespondents}
                loading={respondentsCohortLoading}
                disabledReason={accessDisabledReason}
                tooltip="Send a one-time email to the people behind the responses shown"
                data-attr="survey-email-respondents"
            >
                {hasActiveFilters ? 'Email these respondents' : 'Email respondents'}
            </LemonButton>
        </>
    )
}

import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { surveyRespondentsBroadcastLogic } from './surveyRespondentsBroadcastLogic'

export function SurveyRespondentsBroadcastButton({ surveyId }: { surveyId: string }): JSX.Element {
    const logic = surveyRespondentsBroadcastLogic({ surveyId })
    const { respondentsCohortLoading, hasActiveFilters } = useValues(logic)
    const { emailRespondents } = useActions(logic)
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSend />}
            onClick={emailRespondents}
            loading={respondentsCohortLoading}
            disabledReason={messageAudienceAccessDisabledReason()}
            tooltip="Send a one-time email to the people behind the responses shown"
            data-attr="survey-email-respondents"
        >
            {hasActiveFilters ? 'Email these respondents' : 'Email respondents'}
        </LemonButton>
    )
}

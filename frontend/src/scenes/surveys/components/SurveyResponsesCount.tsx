import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { surveysLogic } from 'scenes/surveys/surveysLogic'

export function SurveyResponsesCount({ surveyId }: { surveyId: string }): JSX.Element {
    const { surveysResponsesCount, surveysResponsesCountLoading, responsesCountFailedSurveyIds } =
        useValues(surveysLogic)
    const { loadResponsesCount } = useActions(surveysLogic)

    if (surveysResponsesCountLoading) {
        return <Spinner />
    }

    if (responsesCountFailedSurveyIds.has(surveyId)) {
        return (
            <LemonButton
                size="xsmall"
                type="tertiary"
                status="danger"
                icon={<IconRefresh />}
                tooltip="Couldn't load the response count. Click to try again."
                onClick={() => loadResponsesCount([surveyId])}
                data-attr="survey-responses-count-retry"
            >
                Retry
            </LemonButton>
        )
    }

    return <div>{surveysResponsesCount[surveyId] ?? 0}</div>
}

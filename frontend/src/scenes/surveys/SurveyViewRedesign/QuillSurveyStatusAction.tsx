import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { openResumeSurveyDialog, openStopSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyStatus } from 'scenes/surveys/surveysLogic'

import { AccessControlLevel, AccessControlResourceType, ProgressStatus } from '~/types'

export function QuillSurveyStatusAction(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { stopSurvey, resumeSurvey } = useActions(surveyLogic)
    const status = getSurveyStatus(survey)

    // Drafts launch from the review's launch bar, so the header keeps one primary action.
    if (status === ProgressStatus.Draft || survey.archived) {
        return null
    }

    if (status === ProgressStatus.Complete) {
        return (
            <AccessControlAction
                resourceType={AccessControlResourceType.Survey}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={survey.user_access_level}
            >
                <Button variant="outline" onClick={() => openResumeSurveyDialog(survey, () => resumeSurvey())}>
                    Resume
                </Button>
            </AccessControlAction>
        )
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Survey}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={survey.user_access_level}
        >
            <Button
                data-attr="stop-survey"
                variant="destructive-outline"
                onClick={() => openStopSurveyDialog(() => stopSurvey())}
            >
                Stop
            </Button>
        </AccessControlAction>
    )
}

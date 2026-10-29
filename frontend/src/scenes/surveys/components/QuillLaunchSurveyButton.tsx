import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { openLaunchSurveyDialog } from './launchSurveyDialog'

export function QuillLaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey, surveyWarnings } = useValues(surveyLogic)
    const { launchSurvey } = useActions(surveyLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Survey}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={survey.user_access_level}
        >
            <Button
                variant="primary"
                data-attr="launch-survey"
                onClick={() => openLaunchSurveyDialog({ survey, surveyWarnings, launchSurvey })}
            >
                {children}
            </Button>
        </AccessControlAction>
    )
}

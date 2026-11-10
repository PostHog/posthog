import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { openLaunchSurveyDialog } from './launchSurveyDialog'

export function LaunchSurveyButton({
    children = 'Launch',
    size = 'small',
}: {
    children?: ReactNode
    size?: LemonButtonProps['size']
}): JSX.Element {
    const { survey, surveyWarnings } = useValues(surveyLogic)
    const { launchSurvey } = useActions(surveyLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Survey}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={survey.user_access_level}
        >
            <LemonButton
                type="primary"
                data-attr="launch-survey"
                size={size}
                onClick={() => openLaunchSurveyDialog({ survey, surveyWarnings, launchSurvey })}
            >
                {children}
            </LemonButton>
        </AccessControlAction>
    )
}

import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { doesSurveyHaveDisplayConditions } from 'scenes/surveys/utils'

import { SurveyType } from '~/types'

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { showSurveysDisabledBanner } = useValues(surveysLogic)
    const { launchSurvey } = useActions(surveyLogic)

    return (
        <LemonButton
            type="primary"
            data-attr="launch-survey"
            disabledReason={
                showSurveysDisabledBanner && survey.type !== SurveyType.API
                    ? 'Please enable surveys in the banner below before launching'
                    : undefined
            }
            onClick={() => {
                LemonDialog.open({
                    title: 'Launch this survey?',
                    content: (
                        <div className="text-sm text-secondary">
                            The survey will immediately start displaying to{' '}
                            {doesSurveyHaveDisplayConditions(survey)
                                ? 'users matching the display conditions'
                                : 'all your users'}
                            .
                        </div>
                    ),
                    primaryButton: {
                        children: 'Launch',
                        type: 'primary',
                        onClick: () => launchSurvey(),
                        size: 'small',
                    },
                    secondaryButton: {
                        children: 'Cancel',
                        type: 'tertiary',
                        size: 'small',
                    },
                })
            }}
        >
            {children}
        </LemonButton>
    )
}

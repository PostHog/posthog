import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBanner, LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { doesSurveyHaveDisplayConditions } from 'scenes/surveys/utils'

import { AccessControlLevel, AccessControlResourceType, SurveyType } from '~/types'
import dayjs from 'dayjs'
import { ProductIntentContext } from '~/queries/schema/schema-general'
import SurveyLaunchSchedule from 'scenes/surveys/components/SurveyLaunchSchedule';

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey, surveyWarnings } = useValues(surveyLogic)
    console.log('survey', survey)
    const { showSurveysDisabledBanner } = useValues(surveysLogic)
    const { updateSurvey } = useActions(surveyLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Survey}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={survey.user_access_level}
        >
            <LemonButton
                type="primary"
                data-attr="launch-survey"
                disabledReason={
                    showSurveysDisabledBanner && survey.type !== SurveyType.API
                        ? 'Please enable surveys in the banner below before launching'
                        : undefined
                }
                size="small"
                onClick={() => {
                    LemonDialog.open({
                        title: 'Launch this survey?',
                        content: (
                            <div>
                                <div className="text-sm text-secondary">
                                    The survey will immediately start displaying to{' '}
                                    {doesSurveyHaveDisplayConditions(survey)
                                        ? 'users matching the display conditions'
                                        : 'all your users'}
                                    .
                                </div>
                                {survey.scheduled_start_datetime && !survey.start_date && (
                                    <LemonBanner type="info" hideIcon className="mt-5">
                                        <div>
                                            This survey is scheduled to launch{' '}
                                            <TZLabel time={survey.scheduled_start_datetime} />. Proceed to launch it
                                            immediately.
                                        </div>
                                    </LemonBanner>
                                )}
                                <SdkVersionWarnings warnings={surveyWarnings} />
                                <SurveyLaunchSchedule />
                            </div>
                        ),
                        primaryButton: {
                            children: 'Launch',
                            type: 'primary',
                            onClick: () => updateSurvey({ id: survey.id, start_date: dayjs().toISOString(), intentContext: ProductIntentContext.SURVEY_LAUNCHED }),
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
        </AccessControlAction>
    )
}

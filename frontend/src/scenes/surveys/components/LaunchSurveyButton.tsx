import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { SurveyStartDialog } from 'scenes/surveys/components/SurveyLifecycleDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { buildSurveyStartUpdatePayload } from 'scenes/surveys/surveyScheduling'
import { getSurveyWarnings } from 'scenes/surveys/surveyVersionRequirements'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { surveysSdkLogic } from 'scenes/surveys/surveysSdkLogic'
import { doesSurveyHaveDisplayConditions } from 'scenes/surveys/utils'

import { ProductIntentContext } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, Survey, SurveyType } from '~/types'

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { updateSurvey } = useActions(surveyLogic)
    const { showSurveysDisabledBanner } = useValues(surveysLogic)
    const { teamSdkVersions } = useValues(surveysSdkLogic)
    const [isLaunchDialogOpen, setIsLaunchDialogOpen] = useState(false)

    const surveyWarnings = useMemo(() => {
        return typeof (survey as Survey).id === 'number' ? getSurveyWarnings(survey as Survey, teamSdkVersions) : []
    }, [survey, teamSdkVersions])

    const closeDialog = useCallback(() => {
        setIsLaunchDialogOpen(false)
    }, [])

    return (
        <>
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
                    onClick={() => setIsLaunchDialogOpen(true)}
                >
                    {children}
                </LemonButton>
            </AccessControlAction>

            <SurveyStartDialog
                isOpen={isLaunchDialogOpen}
                description={`Start displaying to ${doesSurveyHaveDisplayConditions(survey) ? 'users matching the display conditions' : 'all your users'}:`}
                initialScheduledTime={survey.scheduled_start_datetime || undefined}
                afterPickerContent={<SdkVersionWarnings warnings={surveyWarnings} />}
                onSubmit={async (scheduledStartTime) => {
                    await updateSurvey({
                        id: survey.id,
                        intentContext: ProductIntentContext.SURVEY_LAUNCHED,
                        ...buildSurveyStartUpdatePayload(scheduledStartTime, dayjs().toISOString()),
                    } as Partial<Survey>)
                }}
                onClose={closeDialog}
            />
        </>
    )
}

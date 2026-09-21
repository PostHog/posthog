import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { getSurveyStatus } from 'scenes/surveys/surveysLogic'

import { ProgressStatus, Survey } from '~/types'

export function getSurveyStatusTagType(status: ProgressStatus): LemonTagType {
    return {
        running: 'success',
        draft: 'default',
        complete: 'completion',
    }[status] as LemonTagType
}

export function SurveyStatusTag({ survey }: { survey: Pick<Survey, 'start_date' | 'end_date'> }): JSX.Element {
    const status = getSurveyStatus(survey)
    return (
        <LemonTag type={getSurveyStatusTagType(status)} className="font-semibold" data-attr="status">
            {status.toUpperCase()}
        </LemonTag>
    )
}

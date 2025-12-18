import { IconClock } from '@posthog/icons'
import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getSurveyScheduledChange, getSurveyStatus } from 'scenes/surveys/surveysLogic'

import { ProgressStatus, Survey } from '~/types'

export function SurveyStatusTag({
    survey,
}: {
    survey: Pick<Survey, 'start_date' | 'end_date' | 'scheduled_start_datetime' | 'scheduled_end_datetime'>
}): JSX.Element {
    const statusColors = {
        running: 'success',
        draft: 'default',
        complete: 'completion',
    } as Record<ProgressStatus, LemonTagType>

    const status = getSurveyStatus(survey)

    const scheduledChange = getSurveyScheduledChange(survey)
    const scheduledLabel = scheduledChange
        ? scheduledChange.type === 'start'
            ? 'Scheduled start'
            : scheduledChange.type === 'resume'
              ? 'Scheduled resume'
              : 'Scheduled end'
        : null

    return (
        <div className="flex items-center gap-1">
            <LemonTag type={statusColors[status]} className="font-semibold" data-attr="status">
                {status.toUpperCase()}
            </LemonTag>
            {scheduledChange && scheduledLabel && (
                <Tooltip
                    title={
                        <span className="flex items-center gap-1">
                            {scheduledLabel}: <TZLabel time={scheduledChange.scheduledAt} />
                        </span>
                    }
                >
                    <span className="flex items-center" data-attr="status-scheduled" aria-label={scheduledLabel}>
                        <IconClock className="text-muted" />
                    </span>
                </Tooltip>
            )}
        </div>
    )
}

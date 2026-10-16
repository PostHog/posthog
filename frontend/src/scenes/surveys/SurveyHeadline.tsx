import { useActions, useValues } from 'kea'

import { IconRefresh, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { surveyLogic } from './surveyLogic'

export function SurveyHeadline(): JSX.Element | null {
    const { survey, surveyHeadlineLoading, dataProcessingAccepted } = useValues(surveyLogic)
    const { loadSurveyHeadline } = useActions(surveyLogic)

    // An organization without AI consent cannot use this feature. A summary that was generated
    // before the organization turned AI off stays hidden, because the results page must agree
    // with the organization setting.
    if (!dataProcessingAccepted) {
        return null
    }

    if (!surveyHeadlineLoading && !survey.headline_summary) {
        return null
    }

    const refreshButton = (
        <LemonButton
            type="tertiary"
            size="xsmall"
            icon={<IconRefresh />}
            onClick={() => loadSurveyHeadline(true)}
            tooltip={`Regenerate summary (last generated with ${survey.headline_response_count} responses)`}
        />
    )

    return (
        <div className="p-4 border rounded bg-bg-light flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                    <IconSparkles className="text-lg" style={{ color: '#F7B955' }} />
                    <span className="text-xs font-semibold uppercase text-text-secondary">
                        What your responses are saying
                    </span>
                </div>
                {!surveyHeadlineLoading && refreshButton}
            </div>
            {surveyHeadlineLoading ? (
                <LemonSkeleton className="h-6 w-full" />
            ) : (
                <div className="text-base">{survey.headline_summary}</div>
            )}
        </div>
    )
}

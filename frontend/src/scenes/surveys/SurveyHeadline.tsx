import { useActions, useValues } from 'kea'

import { IconRefresh, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { surveyLogic } from './surveyLogic'

export function SurveyHeadline(): JSX.Element | null {
    const { survey, surveyHeadlineLoading, dataProcessingAccepted } = useValues(surveyLogic)
    const { loadSurveyHeadline } = useActions(surveyLogic)

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
            disabledReason={!dataProcessingAccepted ? 'AI data processing must be approved to regenerate' : undefined}
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
                {!surveyHeadlineLoading &&
                    (dataProcessingAccepted ? (
                        refreshButton
                    ) : (
                        <AIConsentPopoverWrapper showArrow onApprove={() => loadSurveyHeadline(true)}>
                            {refreshButton}
                        </AIConsentPopoverWrapper>
                    ))}
            </div>
            {surveyHeadlineLoading ? (
                <LemonSkeleton className="h-6 w-full" />
            ) : (
                <div className="text-base">{survey.headline_summary}</div>
            )}
        </div>
    )
}

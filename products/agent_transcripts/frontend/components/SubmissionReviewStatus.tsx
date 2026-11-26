import { TZLabel } from 'lib/components/TZLabel'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { SubmissionStatusMessage } from './SubmissionStatusMessage'

export interface SubmissionReviewStatusProps {
    submission: CustomerSubmissionStateApi
    variant: AgentTranscriptRequestVariant | null
}

/** What an organization sees once its transcript is uploaded: in review, approved or declined. */
export function SubmissionReviewStatus({ submission, variant }: SubmissionReviewStatusProps): JSX.Element | null {
    switch (submission.status) {
        case SubmissionStatusEnumApi.Submitted:
            return (
                <SubmissionStatusMessage title="Your transcript is in review" data-attr="agent-transcript-in-review">
                    <p className="m-0">
                        The PostHog team is reviewing <strong translate="no">{submission.original_filename}</strong>,
                        which you uploaded{' '}
                        {submission.submitted_at ? <TZLabel time={submission.submitted_at} /> : <span>recently</span>}.
                    </p>
                    <p className="m-0">Thanks for sharing it.</p>
                </SubmissionStatusMessage>
            )
        case SubmissionStatusEnumApi.Approved:
            return (
                <SubmissionStatusMessage title="We approved your transcript" data-attr="agent-transcript-approved">
                    <p className="m-0">
                        {variant === 'test'
                            ? 'Thanks for sharing it. Your $20 code for the PostHog merch store is on its way to your email.'
                            : 'Thanks for sharing it. It helps us improve how agents set up PostHog.'}
                    </p>
                </SubmissionStatusMessage>
            )
        case SubmissionStatusEnumApi.Declined:
            return (
                <SubmissionStatusMessage title="We couldn't use your transcript" data-attr="agent-transcript-declined">
                    {submission.review_message && (
                        <p className="m-0 whitespace-pre-wrap">{submission.review_message}</p>
                    )}
                    <p className="m-0">Thanks for taking the time to share it.</p>
                </SubmissionStatusMessage>
            )
        default:
            return null
    }
}

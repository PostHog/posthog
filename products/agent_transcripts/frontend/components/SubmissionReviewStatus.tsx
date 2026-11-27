import { Callout, CalloutContent, CalloutDescription, CalloutTitle, Highlight, Text } from '@posthog/quill'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { SubmittedFileItem } from './SubmittedFileItem'
import { TranscriptHero } from './TranscriptHero'
import { ApprovedHog, DeclinedHog, InReviewHog } from './transcriptHogs'

export interface SubmissionReviewStatusProps {
    submission: CustomerSubmissionStateApi
    variant: AgentTranscriptRequestVariant | null
}

/** What an organization sees once its transcript is uploaded: in review, approved or declined. */
export function SubmissionReviewStatus({ submission, variant }: SubmissionReviewStatusProps): JSX.Element | null {
    const fileProps = { fileName: submission.original_filename, submittedAt: submission.submitted_at }

    switch (submission.status) {
        case SubmissionStatusEnumApi.Submitted:
            return (
                <TranscriptHero
                    hog={<InReviewHog className="size-full" loading="eager" />}
                    title="Your transcript is in review"
                    data-attr="agent-transcript-in-review"
                >
                    <Text variant="muted" render={<p className="m-0" />}>
                        The PostHog team is reviewing the file you uploaded. Thanks for sharing it.
                    </Text>
                    <SubmittedFileItem {...fileProps} statusLabel="In review" statusVariant="info" />
                </TranscriptHero>
            )
        case SubmissionStatusEnumApi.Approved:
            return (
                <TranscriptHero
                    hog={<ApprovedHog className="size-full" loading="eager" />}
                    title={
                        <>
                            We{' '}
                            <Highlight color="green" animate>
                                approved
                            </Highlight>{' '}
                            your transcript
                        </>
                    }
                    data-attr="agent-transcript-approved"
                >
                    <Text variant="muted" render={<p className="m-0" />}>
                        {variant === 'test'
                            ? 'Thanks for sharing it. Your $20 code for the PostHog merch store is on its way to your email.'
                            : 'Thanks for sharing it. It helps us improve how agents set up PostHog.'}
                    </Text>
                    <SubmittedFileItem {...fileProps} statusLabel="Approved" statusVariant="success" />
                </TranscriptHero>
            )
        case SubmissionStatusEnumApi.Declined:
            return (
                <TranscriptHero
                    hog={<DeclinedHog className="size-full" loading="eager" />}
                    title="We couldn't use your transcript"
                    data-attr="agent-transcript-declined"
                >
                    <Text variant="muted" render={<p className="m-0" />}>
                        Thanks for taking the time to share it.
                    </Text>
                    {submission.review_message && (
                        <Callout className="w-full max-w-md text-left">
                            <CalloutContent>
                                <CalloutTitle>Note from the PostHog team</CalloutTitle>
                                <CalloutDescription className="whitespace-pre-wrap">
                                    {submission.review_message}
                                </CalloutDescription>
                            </CalloutContent>
                        </Callout>
                    )}
                    <SubmittedFileItem {...fileProps} statusLabel="Declined" statusVariant="default" />
                </TranscriptHero>
            )
        default:
            return null
    }
}

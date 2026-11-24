import { useActions } from 'kea'

import { Button, Heading, Text } from '@posthog/quill'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUS_NEXT_STEPS, oauthAppActions } from '../oauthAppProvisioningStatus'
import { QuillProvisioningStatusBadge } from '../QuillProvisioningStatusBadge'
import { oauthApplicationLogic } from './oauthApplicationLogic'
import { QuillOAuthAppReviewNoteForm } from './QuillOAuthAppReviewNoteForm'
import { QuillOAuthAppReviewProgress } from './QuillOAuthAppReviewProgress'
import { QuillOAuthAppReviewTimeline } from './QuillOAuthAppReviewTimeline'

export function QuillOAuthApplicationReview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { contactSupport } = useActions(oauthApplicationLogic({ id: app.id }))
    const { takesANote, needsSupport, canRequestVerification } = oauthAppActions(app)
    const review = app.provisioning_review

    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <Heading size="sm" render={<h2 className="m-0" />}>
                    Provisioning review
                </Heading>
                <QuillProvisioningStatusBadge status={app.provisioning_status} />
            </div>
            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                {PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}
            </Text>
            {review && <QuillOAuthAppReviewProgress review={review} />}
            {review && <QuillOAuthAppReviewTimeline events={review.timeline} />}
            {takesANote && <QuillOAuthAppReviewNoteForm app={app} />}
            {(needsSupport || canRequestVerification) && (
                <div className="flex flex-wrap gap-2">
                    {needsSupport && (
                        <Button
                            variant="outline"
                            onClick={() => contactSupport('review')}
                            data-attr="oauth-app-review-contact-support"
                        >
                            Contact support about this review
                        </Button>
                    )}
                    {canRequestVerification && (
                        <Button
                            variant="outline"
                            onClick={() => contactSupport('verification')}
                            data-attr="oauth-app-request-verification"
                            tooltip="People who connect an unverified application to PostHog see a warning that PostHog has not verified it."
                        >
                            Request verification
                        </Button>
                    )}
                </div>
            )}
        </section>
    )
}

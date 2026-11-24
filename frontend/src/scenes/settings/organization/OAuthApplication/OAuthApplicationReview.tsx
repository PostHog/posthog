import { useActions } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import {
    PROVISIONING_STATUS_LABELS,
    PROVISIONING_STATUS_NEXT_STEPS,
    PROVISIONING_STATUS_TAG_TYPES,
    oauthAppActions,
} from '../oauthAppProvisioningStatus'
import { oauthAppsLogic } from '../oauthAppsLogic'
import { OAuthAppReviewNoteForm } from './OAuthAppReviewNoteForm'
import { OAuthAppReviewProgress } from './OAuthAppReviewProgress'
import { OAuthAppReviewTimeline } from './OAuthAppReviewTimeline'

export function OAuthApplicationReview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { contactSupport } = useActions(oauthAppsLogic)
    const { takesANote, needsSupport, canRequestVerification } = oauthAppActions(app)
    const review = app.provisioning_review

    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold m-0">Provisioning review</h2>
                <LemonTag type={PROVISIONING_STATUS_TAG_TYPES[app.provisioning_status]}>
                    {PROVISIONING_STATUS_LABELS[app.provisioning_status]}
                </LemonTag>
            </div>
            <p className="m-0 text-secondary">{PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}</p>
            {review && <OAuthAppReviewProgress review={review} />}
            {review && <OAuthAppReviewTimeline events={review.timeline} />}
            {takesANote && <OAuthAppReviewNoteForm app={app} />}
            {(needsSupport || canRequestVerification) && (
                <div className="flex flex-wrap gap-2">
                    {needsSupport && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => contactSupport(app, 'review')}
                            data-attr="oauth-app-review-contact-support"
                        >
                            Contact support about this review
                        </LemonButton>
                    )}
                    {canRequestVerification && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => contactSupport(app, 'verification')}
                            data-attr="oauth-app-request-verification"
                            tooltip="People who connect an unverified application to PostHog see a warning that PostHog has not verified it."
                        >
                            Request verification
                        </LemonButton>
                    )}
                </div>
            )}
        </section>
    )
}

import { useActions } from 'kea'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import {
    PROVISIONING_STATUS_LABELS,
    PROVISIONING_STATUS_NEXT_STEPS,
    PROVISIONING_STATUS_TAG_TYPES,
    oauthAppActions,
} from '../oauthAppProvisioningStatus'
import { PROVISIONING_REVIEW_EXPLAINER, SIGNING_KEY_REQUIRED } from './oauthApplicationLabels'
import { oauthApplicationLogic } from './oauthApplicationLogic'
import { OAuthAppReviewNoteForm } from './OAuthAppReviewNoteForm'
import { OAuthAppReviewProgress } from './OAuthAppReviewProgress'
import { OAuthAppReviewTimeline } from './OAuthAppReviewTimeline'

export function OAuthApplicationReview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { contactSupport } = useActions(oauthApplicationLogic({ id: app.id }))
    const { takesANote, needsSupport } = oauthAppActions(app)
    const review = app.provisioning_review

    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold m-0">Provisioning review</h2>
                <LemonTag type={PROVISIONING_STATUS_TAG_TYPES[app.provisioning_status]}>
                    {PROVISIONING_STATUS_LABELS[app.provisioning_status]}
                </LemonTag>
            </div>
            <p className="m-0 text-secondary">{PROVISIONING_REVIEW_EXPLAINER}</p>
            {app.registration.needs_signing_key && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'How to sign requests',
                        to: SIGNING_KEY_REQUIRED.docsUrl,
                        targetBlank: true,
                    }}
                >
                    <strong>{SIGNING_KEY_REQUIRED.title}.</strong> {SIGNING_KEY_REQUIRED.description}
                </LemonBanner>
            )}
            <p className="m-0">{PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}</p>
            {review && <OAuthAppReviewProgress review={review} />}
            {review && <OAuthAppReviewTimeline events={review.timeline} />}
            {takesANote && <OAuthAppReviewNoteForm app={app} />}
            {needsSupport && (
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => contactSupport('review')}
                        data-attr="oauth-app-review-contact-support"
                    >
                        Contact support about this review
                    </LemonButton>
                </div>
            )}
        </section>
    )
}

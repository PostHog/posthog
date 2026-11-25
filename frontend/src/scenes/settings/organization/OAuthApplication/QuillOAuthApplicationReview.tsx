import { useActions } from 'kea'

import { Button, Heading, Item, ItemActions, ItemContent, ItemDescription, ItemTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUS_NEXT_STEPS, oauthAppActions } from '../oauthAppProvisioningStatus'
import { QuillProvisioningStatusBadge } from '../QuillProvisioningStatusBadge'
import { PROVISIONING_REVIEW_EXPLAINER, SIGNING_KEY_REQUIRED } from './oauthApplicationLabels'
import { oauthApplicationLogic } from './oauthApplicationLogic'
import { QuillOAuthAppReviewNoteForm } from './QuillOAuthAppReviewNoteForm'
import { QuillOAuthAppReviewProgress } from './QuillOAuthAppReviewProgress'
import { QuillOAuthAppReviewTimeline } from './QuillOAuthAppReviewTimeline'

export function QuillOAuthApplicationReview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { contactSupport } = useActions(oauthApplicationLogic({ id: app.id }))
    const { takesANote, needsSupport } = oauthAppActions(app)
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
                {PROVISIONING_REVIEW_EXPLAINER}
            </Text>
            {app.registration.needs_signing_key && (
                <Item tone="warning" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemTitle>{SIGNING_KEY_REQUIRED.title}</ItemTitle>
                        <ItemDescription>{SIGNING_KEY_REQUIRED.description}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            render={<LinkPrimitive to={SIGNING_KEY_REQUIRED.docsUrl} target="_blank" />}
                        >
                            How to sign requests
                        </Button>
                    </ItemActions>
                </Item>
            )}
            <Text size="sm" render={<p className="m-0" />}>
                {PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}
            </Text>
            {review && <QuillOAuthAppReviewProgress review={review} />}
            {review && <QuillOAuthAppReviewTimeline events={review.timeline} />}
            {takesANote && <QuillOAuthAppReviewNoteForm app={app} />}
            {needsSupport && (
                <div>
                    <Button
                        variant="outline"
                        onClick={() => contactSupport('review')}
                        data-attr="oauth-app-review-contact-support"
                    >
                        Contact support about this review
                    </Button>
                </div>
            )}
        </section>
    )
}

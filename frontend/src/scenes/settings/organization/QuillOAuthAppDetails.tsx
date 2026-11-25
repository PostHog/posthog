import { useActions } from 'kea'

import { Button, Text } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUS_NEXT_STEPS, oauthAppActions } from './oauthAppProvisioningStatus'
import { oauthAppsLogic } from './oauthAppsLogic'
import { QuillCopyableCode } from './QuillCopyableCode'
import { QuillOAuthAppReviewNoteForm } from './QuillOAuthAppReviewNoteForm'
import { QuillOAuthAppReviewProgress } from './QuillOAuthAppReviewProgress'
import { QuillOAuthAppReviewTimeline } from './QuillOAuthAppReviewTimeline'
import { QuillProvisioningStatusBadge } from './QuillProvisioningStatusBadge'

export function QuillOAuthAppDetails({ app }: { app: OrganizationOAuthApplicationApi }): JSX.Element {
    const { contactSupport } = useActions(oauthAppsLogic)

    const review = app.provisioning_review
    const { showsProvisioning, takesANote, needsSupport, canRequestVerification } = oauthAppActions(app)
    const redirectUris = app.redirect_uris_list ?? []

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="semibold" render={<span />}>
                    Redirect URIs
                </Text>
                {redirectUris.length === 0 ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        None
                    </Text>
                ) : (
                    redirectUris.map((uri) => (
                        <QuillCopyableCode
                            key={uri}
                            value={uri}
                            label="Copy redirect URI"
                            onCopy={() => void copyToClipboard(uri, 'redirect URI')}
                        />
                    ))
                )}
            </div>

            {showsProvisioning && (
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" weight="semibold" render={<span />}>
                            Provisioning
                        </Text>
                        <QuillProvisioningStatusBadge status={app.provisioning_status} />
                    </div>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}
                    </Text>
                </div>
            )}

            {review && <QuillOAuthAppReviewProgress review={review} />}

            {review && <QuillOAuthAppReviewTimeline events={review.timeline} />}

            {takesANote && <QuillOAuthAppReviewNoteForm app={app} />}

            {(needsSupport || canRequestVerification) && (
                <div className="flex flex-wrap gap-2">
                    {needsSupport && (
                        <Button
                            variant="outline"
                            onClick={() => contactSupport(app, 'review')}
                            data-attr="oauth-app-review-contact-support"
                        >
                            Contact support about this review
                        </Button>
                    )}
                    {canRequestVerification && (
                        <Button
                            variant="outline"
                            onClick={() => contactSupport(app, 'verification')}
                            data-attr="oauth-app-request-verification"
                            tooltip="People who connect an unverified application to PostHog see a warning that PostHog has not verified it."
                        >
                            Request verification
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}

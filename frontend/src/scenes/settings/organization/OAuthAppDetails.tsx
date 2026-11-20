import { useActions } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import {
    PROVISIONING_STATUSES_NEEDING_SUPPORT,
    PROVISIONING_STATUS_LABELS,
    PROVISIONING_STATUS_NEXT_STEPS,
    PROVISIONING_STATUS_TAG_TYPES,
} from './oauthAppProvisioningStatus'
import { oauthAppsLogic } from './oauthAppsLogic'

export function OAuthAppDetails({ app }: { app: OrganizationOAuthApplicationApi }): JSX.Element {
    const { contactSupport } = useActions(oauthAppsLogic)
    const review = app.provisioning_review
    const canRequestVerification = app.is_cimd_client && !app.is_verified
    const needsSupport = PROVISIONING_STATUSES_NEEDING_SUPPORT.has(app.provisioning_status)
    const showsProvisioning = app.is_cimd_client || app.provisioning_status !== 'not_a_partner'
    const redirectUris = app.redirect_uris_list ?? []

    return (
        <div className="flex flex-col gap-3 p-2">
            <div className="flex flex-col gap-1">
                <span className="font-semibold">Redirect URIs</span>
                {redirectUris.length === 0 ? (
                    <span className="text-muted">None</span>
                ) : (
                    redirectUris.map((uri) => (
                        <CopyToClipboardInline key={uri} description="redirect URI" className="font-mono text-xs">
                            {uri}
                        </CopyToClipboardInline>
                    ))
                )}
            </div>
            {showsProvisioning && (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">Provisioning</span>
                        <LemonTag type={PROVISIONING_STATUS_TAG_TYPES[app.provisioning_status]}>
                            {PROVISIONING_STATUS_LABELS[app.provisioning_status]}
                        </LemonTag>
                    </div>
                    <p className="m-0 text-secondary">{PROVISIONING_STATUS_NEXT_STEPS[app.provisioning_status]}</p>
                </>
            )}
            {review && (
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                    <span>
                        <span className="text-secondary">Registered </span>
                        <TZLabel time={review.opened_at} />
                    </span>
                    {review.decided_at && (
                        <span>
                            <span className="text-secondary">Decided </span>
                            <TZLabel time={review.decided_at} />
                        </span>
                    )}
                </div>
            )}
            {review?.partner_message && (
                <div className="border rounded p-3 bg-surface-secondary">
                    <div className="text-xs font-semibold text-secondary mb-1">Message from PostHog</div>
                    <p className="m-0 whitespace-pre-wrap">{review.partner_message}</p>
                </div>
            )}
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
        </div>
    )
}

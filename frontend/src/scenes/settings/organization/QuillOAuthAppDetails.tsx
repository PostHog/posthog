import { useActions } from 'kea'

import { Button, Item, ItemContent, ItemTitle, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUSES_NEEDING_SUPPORT, PROVISIONING_STATUS_NEXT_STEPS } from './oauthAppProvisioningStatus'
import { oauthAppsLogic } from './oauthAppsLogic'
import { QuillCopyableCode } from './QuillCopyableCode'
import { QuillProvisioningStatusBadge } from './QuillProvisioningStatusBadge'

export function QuillOAuthAppDetails({ app }: { app: OrganizationOAuthApplicationApi }): JSX.Element {
    const { contactSupport } = useActions(oauthAppsLogic)

    const review = app.provisioning_review
    const canRequestVerification = app.is_cimd_client && !app.is_verified
    const needsSupport = PROVISIONING_STATUSES_NEEDING_SUPPORT.has(app.provisioning_status)
    const showsProvisioning = app.is_cimd_client || app.provisioning_status !== 'not_a_partner'
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

            {review && (
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                    <Text size="xs" render={<span />}>
                        <span className="text-muted-foreground">Registered </span>
                        <TZLabel time={review.opened_at} />
                    </Text>
                    {review.decided_at && (
                        <Text size="xs" render={<span />}>
                            <span className="text-muted-foreground">Decided </span>
                            <TZLabel time={review.decided_at} />
                        </Text>
                    )}
                </div>
            )}

            {review?.partner_message && (
                <Item variant="muted" size="sm">
                    <ItemContent>
                        <ItemTitle>Message from PostHog</ItemTitle>
                        <Text size="xs" render={<p className="m-0 whitespace-pre-wrap" />}>
                            {review.partner_message}
                        </Text>
                    </ItemContent>
                </Item>
            )}

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

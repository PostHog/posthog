import { useActions } from 'kea'

import { Badge, Button, Heading, Text } from '@posthog/quill'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { oauthAppActions } from '../oauthAppProvisioningStatus'
import { VERIFICATION_EXPLAINERS } from './oauthApplicationLabels'
import { oauthApplicationLogic } from './oauthApplicationLogic'

export function QuillOAuthApplicationVerification({
    app,
}: {
    app: OrganizationOAuthApplicationDetailApi
}): JSX.Element {
    const { contactSupport } = useActions(oauthApplicationLogic({ id: app.id }))
    const { canRequestVerification } = oauthAppActions(app)
    const isPartner = app.provisioning_status !== 'not_a_partner'

    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <Heading size="sm" render={<h2 className="m-0" />}>
                    Verification
                </Heading>
                {app.is_verified ? (
                    <Badge variant="success">Verified</Badge>
                ) : (
                    <Badge variant="warning">Not verified</Badge>
                )}
            </div>
            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                {app.is_verified
                    ? VERIFICATION_EXPLAINERS.verified
                    : isPartner
                      ? VERIFICATION_EXPLAINERS.notVerifiedProvisioner
                      : VERIFICATION_EXPLAINERS.notVerified}
            </Text>
            {isPartner && (
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    {VERIFICATION_EXPLAINERS.separateFromProvisioning}
                </Text>
            )}
            {canRequestVerification && (
                <div>
                    <Button
                        variant="outline"
                        onClick={() => contactSupport('verification')}
                        data-attr="oauth-app-request-verification"
                    >
                        Request verification
                    </Button>
                </div>
            )}
        </section>
    )
}

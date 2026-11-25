import { useActions } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { oauthAppActions } from '../oauthAppProvisioningStatus'
import { VERIFICATION_EXPLAINERS } from './oauthApplicationLabels'
import { oauthApplicationLogic } from './oauthApplicationLogic'

export function OAuthApplicationVerification({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { contactSupport } = useActions(oauthApplicationLogic({ id: app.id }))
    const { canRequestVerification } = oauthAppActions(app)
    const isPartner = app.provisioning_status !== 'not_a_partner'

    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold m-0">Verification</h2>
                {app.is_verified ? (
                    <LemonTag type="success">Verified</LemonTag>
                ) : (
                    <LemonTag type="warning">Not verified</LemonTag>
                )}
            </div>
            <p className="m-0 text-secondary">
                {app.is_verified
                    ? VERIFICATION_EXPLAINERS.verified
                    : isPartner
                      ? VERIFICATION_EXPLAINERS.notVerifiedProvisioner
                      : VERIFICATION_EXPLAINERS.notVerified}
            </p>
            {isPartner && <p className="m-0 text-secondary">{VERIFICATION_EXPLAINERS.separateFromProvisioning}</p>}
            {canRequestVerification && (
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => contactSupport('verification')}
                        data-attr="oauth-app-request-verification"
                    >
                        Request verification
                    </LemonButton>
                </div>
            )}
        </section>
    )
}

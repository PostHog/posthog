import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'
import { OAuthScopeList } from 'lib/components/ScopeAccessRow/OAuthScopeList'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'

import type { DeviceGrantDetailsApi } from '~/generated/core/api.schemas'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'
import { DeviceProjectPicker } from './DeviceProjectPicker'

export function DeviceReview({ deviceGrant }: { deviceGrant: DeviceGrantDetailsApi }): JSX.Element {
    const {
        projectId,
        decisionLoading,
        error,
        isStepUp,
        identitySummary,
        scopeGroups,
        requiredScopesNote,
        keptScopes,
    } = useValues(oauthDeviceAuthorizeLogic)
    const { approve, deny, setScopeAccess, setScopeGroupAccess } = useActions(oauthDeviceAuthorizeLogic)

    return (
        <AuthScene notes={AUTH_NOTES.oauthDevice.review}>
            <AuthSceneCard
                top={<OAuthConnectionLogos appName={deviceGrant.client_name} logoUri={deviceGrant.logo_uri} />}
            >
                <AuthCardTitle
                    title={
                        isStepUp
                            ? `${deviceGrant.client_name} wants more access`
                            : `${deviceGrant.client_name} wants to access your PostHog account`
                    }
                    sub="Check that this code matches the one your terminal shows."
                />
                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-center gap-2">
                        <span
                            className="ph-no-capture font-mono text-2xl font-semibold tracking-wider"
                            data-attr="oauth-device-user-code"
                        >
                            {deviceGrant.user_code}
                        </span>
                        {deviceGrant.is_verified && <LemonTag type="success">Verified app</LemonTag>}
                    </div>
                    <AuthBanner variant="warning">
                        Only approve a login you started yourself. If someone sent you this code, deny it: approving
                        gives them access to your account.
                    </AuthBanner>
                    <DeviceProjectPicker />
                    <div className="flex flex-col">
                        <OAuthScopeList
                            identitySummary={identitySummary}
                            groups={scopeGroups}
                            onChangeRow={setScopeAccess}
                            onChangeGroup={setScopeGroupAccess}
                            dataAttrPrefix="oauth-device-scope-group"
                            headerClassName="pb-2 border-b border-border"
                            bodyClassName="pt-2"
                        />
                        {requiredScopesNote && (
                            <p className="m-0 text-secondary" data-attr="oauth-device-required-note">
                                {requiredScopesNote}
                            </p>
                        )}
                    </div>
                    {error && <AuthBanner variant="danger">{error}</AuthBanner>}
                    <div className="grid grid-cols-2 gap-2">
                        <LemonButton
                            type="secondary"
                            data-attr="oauth-device-deny"
                            fullWidth
                            center
                            size="large"
                            onClick={deny}
                            disabledReason={decisionLoading ? 'Sending your answer' : undefined}
                        >
                            Deny
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="oauth-device-approve"
                            fullWidth
                            center
                            size="large"
                            onClick={approve}
                            loading={decisionLoading}
                            disabledReason={
                                projectId === null
                                    ? 'Select a project first'
                                    : keptScopes.length === 0
                                      ? 'Give at least one permission first'
                                      : undefined
                            }
                        >
                            Approve
                        </LemonButton>
                    </div>
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}

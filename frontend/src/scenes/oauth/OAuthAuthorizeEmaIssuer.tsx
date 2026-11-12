import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconWarning } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'

import type { OAuthEmaIssuerConsent, OAuthEmaIssuerConsentOrganization } from '~/types'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

function submitDisabledReason(
    organization: OAuthEmaIssuerConsentOrganization | null,
    isCanceling: boolean
): string | undefined {
    if (!organization) {
        return 'Select an organization'
    }
    return organization.disabled_reason ?? (isCanceling ? 'Processing...' : undefined)
}

function verifiedDomainsLabel(organization: OAuthEmaIssuerConsentOrganization | null): string {
    return organization?.verified_domains.length
        ? organization.verified_domains.join(', ')
        : "this organization's verified domains"
}

export function OAuthAuthorizeEmaIssuer({ consent }: { consent: OAuthEmaIssuerConsent }): JSX.Element {
    const { appName, oauthApplication, oauthAuthorization, isOauthAuthorizationSubmitting, isCanceling, user } =
        useValues(oauthAuthorizeLogic)
    const { cancel, submitOauthAuthorization, setOauthAuthorizationValue } = useActions(oauthAuthorizeLogic)

    const selectedOrganizationId = oauthAuthorization.scoped_organizations[0] ?? null
    const selectedOrganization = consent.organizations.find((org) => org.id === selectedOrganizationId) ?? null
    const hasEligibleOrganization = consent.organizations.some((org) => !org.disabled_reason)

    return (
        <>
            <div className="shrink-0 mb-3">
                <AuthCardTitle
                    title={`Set up enterprise-managed auth for ${appName}`}
                    sub={`${appName} is asking to become a trusted identity provider for a PostHog organization.`}
                    className="mb-2"
                />
                {user && (
                    <div className="flex items-center justify-center gap-1.5 min-w-0 text-sm text-muted">
                        <ProfilePicture user={user} size="sm" className="shrink-0" />
                        <span className="truncate">
                            <span className="font-semibold text-primary">{user.email}</span>
                            <span>{` · ${window.location.host}`}</span>
                        </span>
                    </div>
                )}
            </div>

            <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization" className="flex flex-col min-h-0">
                <div className="AuthScene__card flex flex-col min-h-0 overflow-hidden">
                    <div className="flex flex-col gap-4 p-4 sm:p-6 min-h-0 overflow-y-auto">
                        {!oauthApplication?.is_verified && (
                            <div className="flex items-center gap-2 p-3 bg-warning-highlight border border-warning rounded text-sm">
                                <IconWarning className="text-warning shrink-0" />
                                <span>
                                    <strong>Unverified application.</strong> This application has not been verified by
                                    PostHog. Don't continue unless you set this up yourself.
                                </span>
                            </div>
                        )}

                        <div className="flex flex-col gap-2">
                            <LemonLabel>Organization</LemonLabel>
                            <LemonSelect
                                fullWidth
                                placeholder="Select organization"
                                options={consent.organizations.map((org) => ({
                                    value: org.id,
                                    label: org.name,
                                    disabledReason: org.disabled_reason ?? undefined,
                                }))}
                                value={selectedOrganizationId}
                                onChange={(value) => {
                                    if (value) {
                                        setOauthAuthorizationValue('scoped_organizations', [value])
                                    }
                                }}
                                data-attr="oauth-ema-issuer-organization"
                            />
                            {!hasEligibleOrganization && (
                                <p className="text-xs text-muted m-0">
                                    None of your organizations can be set up. Each one shows the reason when you open
                                    the list.
                                </p>
                            )}
                        </div>

                        <LemonBanner type="warning">
                            <div className="flex flex-col gap-2">
                                <strong>Approving gives {appName} sign-in access to this organization.</strong>
                                <ul className="list-disc pl-4 m-0 flex flex-col gap-1">
                                    <li>
                                        PostHog will trust {appName} to say who a person is. Anyone {appName} vouches
                                        for with an email at{' '}
                                        <strong>{verifiedDomainsLabel(selectedOrganization)}</strong> can use PostHog as
                                        the member with that email, with that member's access.
                                    </li>
                                    <li>Members won't be asked to approve each connection.</li>
                                    <li>
                                        Whoever manages sign-in for your {appName} organization decides who that covers.
                                        Only approve if your company manages that organization.
                                    </li>
                                    <li>
                                        To turn this off later, remove the {appName} configuration under XAA in your
                                        organization's authentication settings.
                                    </li>
                                </ul>
                            </div>
                        </LemonBanner>
                    </div>

                    <div className="shrink-0 flex flex-col-reverse sm:flex-row sm:justify-end gap-2 px-4 sm:px-6 py-4 border-t border-border">
                        <LemonButton
                            type="tertiary"
                            status="alt"
                            htmlType="button"
                            data-attr="oauth-ema-issuer-cancel"
                            loading={isCanceling}
                            disabledReason={isOauthAuthorizationSubmitting ? 'Processing...' : undefined}
                            onClick={(e) => {
                                e.preventDefault()
                                cancel()
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            status="danger"
                            htmlType="submit"
                            data-attr="oauth-ema-issuer-submit"
                            loading={isOauthAuthorizationSubmitting}
                            disabledReason={submitDisabledReason(selectedOrganization, isCanceling)}
                            onClick={() => submitOauthAuthorization()}
                        >
                            Trust {appName}
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </>
    )
}

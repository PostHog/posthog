import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconShuffle } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function IdJagSettings(): JSX.Element | null {
    const { isIdJagConfigSubmitting, idJagConfig, isXAAAuthenticationAvailable } = useValues(verifiedDomainsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    if (!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION]) {
        return null
    }

    return (
        <section className="space-y-3">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="flex items-center gap-2">
                        <IconShuffle /> XAA
                    </h2>
                    <p className="text-muted">
                        Configure trusted identity assertions from external applications and integrations.
                    </p>
                </div>
                <LemonTag type={idJagConfig.id_jag_issuer_url ? 'success' : 'muted'}>
                    {idJagConfig.id_jag_issuer_url ? 'Ready' : idJagConfig.id ? 'Needs attention' : 'Not configured'}
                </LemonTag>
            </div>
            <div>
                {!isXAAAuthenticationAvailable ? (
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                        Upgrade your plan to configure XAA.
                    </Link>
                ) : (
                    <Form logic={verifiedDomainsLogic} formKey="idJagConfig" enableFormOnSubmit className="space-y-4">
                        <div className="grid gap-4 lg:grid-cols-2">
                            <LemonField name="name" label="Configuration name">
                                <LemonInput placeholder="WorkOS production" />
                            </LemonField>
                            <IdentityProviderDomainPicker />
                        </div>
                        <div className="grid gap-4 lg:grid-cols-2">
                            <LemonField
                                name="id_jag_issuer_url"
                                label="Identity provider issuer URL"
                                info="This must match the iss claim on ID-JAG tokens for every assigned domain."
                            >
                                <LemonInput
                                    className="ph-ignore-input"
                                    placeholder="https://idp.example.com"
                                    autoComplete="off"
                                />
                            </LemonField>
                            <LemonField
                                name="id_jag_jwks_url"
                                label="JWKS URL (optional)"
                                info="Leave empty to use OIDC discovery from the issuer URL."
                            >
                                <LemonInput
                                    className="ph-ignore-input"
                                    placeholder="https://idp.example.com/.well-known/jwks.json"
                                    autoComplete="off"
                                />
                            </LemonField>
                        </div>
                        <LemonField
                            name="id_jag_allowed_clients"
                            label="Allowed client IDs (optional)"
                            info="Leave empty to allow any client_id."
                        >
                            {({ value, onChange }) => (
                                <LemonInputSelect
                                    value={value || []}
                                    onChange={onChange}
                                    placeholder="Add client IDs"
                                    mode="multiple"
                                    allowCustomValues
                                    options={[]}
                                />
                            )}
                        </LemonField>
                        {!idJagConfig.id_jag_issuer_url && (
                            <LemonBanner type="info">
                                You can save this as a draft. XAA becomes available after an issuer URL is added.
                            </LemonBanner>
                        )}
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isIdJagConfigSubmitting}
                            disabledReason={restrictionReason}
                        >
                            Save XAA settings
                        </LemonButton>
                    </Form>
                )}
            </div>
        </section>
    )
}

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { humanList } from 'lib/utils/strings'

import { ConfigScopeEnumApi, DomainScopeEnumApi, OrganizationDomainApi } from '~/generated/core/api.schemas'

import { IDENTITY_PROVIDER_FEATURES } from './identityProviderConfigUtils'

export function IdentityProviderDomainScope({
    configScope,
    domainScope,
    domains,
    disabled,
    hasSamlDomainScopeConflict,
    showScopeWarning,
}: {
    configScope: ConfigScopeEnumApi
    domainScope: DomainScopeEnumApi
    domains: OrganizationDomainApi[]
    disabled: boolean
    hasSamlDomainScopeConflict: boolean
    showScopeWarning: boolean
}): JSX.Element {
    return (
        <div className="space-y-4">
            {hasSamlDomainScopeConflict && (
                <LemonBanner type="error">
                    This SAML configuration overlaps with another SAML configuration on one or more verified domains.
                    Choose different domains before saving.
                </LemonBanner>
            )}
            {showScopeWarning && (
                <LemonBanner type="warning">
                    Changing this value can affect your{' '}
                    {humanList(
                        Object.values(ConfigScopeEnumApi)
                            .filter((scope) => scope !== configScope)
                            .map((scope) => IDENTITY_PROVIDER_FEATURES[scope].name)
                    )}{' '}
                    configurations.
                </LemonBanner>
            )}
            <LemonField name="domain_scope" label="Domains">
                {({ value, onChange }) => (
                    <LemonRadio
                        value={value}
                        onChange={onChange}
                        options={[
                            {
                                value: DomainScopeEnumApi.All,
                                label: 'All domains',
                                description: 'Apply this configuration to every verified domain in the organization.',
                                disabledReason: disabled ? 'Saving configuration' : undefined,
                                'data-attr': 'identity-provider-domain-scope-all',
                            },
                            {
                                value: DomainScopeEnumApi.Selected,
                                label: 'Selected domains',
                                description: 'Apply this configuration only to the domains you select.',
                                disabledReason: disabled ? 'Saving configuration' : undefined,
                                'data-attr': 'identity-provider-domain-scope-selected',
                            },
                        ]}
                    />
                )}
            </LemonField>
            {domainScope === DomainScopeEnumApi.Selected && (
                <LemonField name="organization_domain_ids">
                    <LemonInputSelect
                        mode="multiple"
                        options={domains.map((domain) => ({
                            key: domain.id,
                            label: domain.is_verified ? domain.domain : `${domain.domain} (pending verification)`,
                        }))}
                        placeholder="Select domains"
                        disabled={disabled}
                    />
                </LemonField>
            )}
        </div>
    )
}

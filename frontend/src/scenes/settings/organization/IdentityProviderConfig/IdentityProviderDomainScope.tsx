import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { DomainScopeEnumApi, OrganizationDomainApi } from '~/generated/core/api.schemas'

export function IdentityProviderDomainScope({
    domainScope,
    domains,
    disabled,
}: {
    domainScope: DomainScopeEnumApi
    domains: OrganizationDomainApi[]
    disabled: boolean
}): JSX.Element {
    return (
        <div className="space-y-4">
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

import { useValues } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function IdentityProviderDomainPicker(): JSX.Element {
    const { verifiedDomainsList } = useValues(verifiedDomainsLogic)

    return (
        <LemonField
            name="domain_ids"
            label="Domains"
            info="Assign this configuration to one or more verified authentication domains."
        >
            {({ value, onChange }) => (
                <LemonInputSelect
                    value={value || []}
                    onChange={onChange}
                    mode="multiple"
                    placeholder="Select domains"
                    options={verifiedDomainsList.map((domain) => ({ key: domain.id, label: domain.domain }))}
                />
            )}
        </LemonField>
    )
}

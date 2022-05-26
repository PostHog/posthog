import { Select } from 'antd'
import { useValues } from 'kea'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SSOProviders } from '~/types'

interface SSOSelectInterface {
    value: SSOProviders | ''
    loading: boolean
    onChange: (value: SSOProviders | '') => void
    samlAvailable: boolean
}

export function SSOSelect({ value, loading, onChange, samlAvailable }: SSOSelectInterface): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight) {
        return null
    }

    return (
        <Select style={{ width: '100%' }} value={value} loading={loading} disabled={loading} onChange={onChange}>
            <Select.Option value="">Don't enforce</Select.Option>
            {Object.keys(preflight.available_social_auth_providers).map((key) => (
                <Select.Option
                    value={key}
                    key={key}
                    disabled={!preflight.available_social_auth_providers[key]}
                    title={
                        preflight.available_social_auth_providers[key] ? undefined : 'This provider is not configured.'
                    }
                >
                    {SocialLoginIcon(key as SSOProviders)} {SSO_PROVIDER_NAMES[key]}
                </Select.Option>
            ))}
            <Select.Option
                value="saml"
                key="saml"
                disabled={!samlAvailable}
                title={samlAvailable ? undefined : 'This provider is not configured.'}
            >
                {SocialLoginIcon('saml')} {SSO_PROVIDER_NAMES['saml']}
            </Select.Option>
        </Select>
    )
}

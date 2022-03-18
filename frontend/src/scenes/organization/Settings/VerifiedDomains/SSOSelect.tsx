import { Select } from 'antd'
import { useValues } from 'kea'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSOProviderNames } from 'lib/constants'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SSOProviders } from '~/types'

interface SSOSelectInterface {
    value: SSOProviders | ''
    loading: boolean
    onChange: (value: SSOProviders | '') => void
}

export function SSOSelect({ value, loading, onChange }: SSOSelectInterface): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight) {
        return null
    }

    return (
        <Select style={{ width: '100%' }} value={value} loading={loading} disabled={loading} onChange={onChange}>
            <Select.Option value="">Not enforced</Select.Option>
            {Object.keys(preflight.available_social_auth_providers).map((key) => (
                <Select.Option
                    value={key}
                    key={key}
                    disabled={!preflight.available_social_auth_providers[key]}
                    title={
                        preflight.available_social_auth_providers[key] ? undefined : 'This provider is not configured.'
                    }
                >
                    {SocialLoginIcon(key as SSOProviders)} {SSOProviderNames[key]}
                </Select.Option>
            ))}
        </Select>
    )
}

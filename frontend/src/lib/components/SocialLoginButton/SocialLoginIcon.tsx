import { GoogleOutlined, GithubOutlined, GitlabOutlined, KeyOutlined } from '@ant-design/icons'
import React from 'react'
import { SSOProviders } from '~/types'

export const SocialLoginIcon = (provider: SSOProviders): JSX.Element | undefined => {
    if (provider === 'google-oauth2') {
        return <GoogleOutlined />
    } else if (provider === 'github') {
        return <GithubOutlined />
    } else if (provider === 'gitlab') {
        return <GitlabOutlined />
    } else if (provider === 'saml') {
        return <KeyOutlined />
    }
}

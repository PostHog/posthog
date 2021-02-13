import { Button } from 'antd'
import React from 'react'
import './index.scss'

export enum SocialProviders {
    Google = 'google-oauth2',
    GitHub = 'github',
    GitLab = 'gitlab',
}

const ProviderNames: Record<SocialProviders, string> = {
    [SocialProviders.Google]: 'Google',
    [SocialProviders.GitHub]: 'GitHub',
    [SocialProviders.GitLab]: 'GitLab',
}

interface SharedProps {
    queryString?: string
}

interface SocialLoginButtonProps extends SharedProps {
    provider: SocialProviders
}

export function SocialLoginButton({ provider, queryString }: SocialLoginButtonProps): JSX.Element {
    return (
        <Button className={`btn-social-login ${provider}`} href={`/login/${provider}/${queryString}`}>
            <div className="btn-social-icon">
                <div className="img" />
            </div>
            Continue with {ProviderNames[provider]}
        </Button>
    )
}

export function SocialLoginButtons({ ...props }: SharedProps): JSX.Element {
    return (
        <div className="social-logins">
            {Object.values(SocialProviders).map((provider) => (
                <div key={provider}>
                    <SocialLoginButton provider={provider} {...props} />
                </div>
            ))}
        </div>
    )
}

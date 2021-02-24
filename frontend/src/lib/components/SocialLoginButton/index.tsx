import { Button } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './index.scss'

enum SocialAuthProviders {
    Google = 'google-oauth2',
    GitHub = 'github',
    GitLab = 'gitlab',
}

const ProviderNames: Record<SocialAuthProviders, string> = {
    [SocialAuthProviders.Google]: 'Google',
    [SocialAuthProviders.GitHub]: 'GitHub',
    [SocialAuthProviders.GitLab]: 'GitLab',
}

interface SharedProps {
    queryString?: string
}

interface SocialLoginButtonProps extends SharedProps {
    provider: SocialAuthProviders
}

interface SocialLoginButtonsProps extends SharedProps {
    title?: string
    caption?: string
}

export function SocialLoginButton({ provider, queryString }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <Button className={`btn-social-login ${provider}`} href={`/login/${provider}/${queryString}`}>
            <div className="btn-social-icon">
                <div className="img" />
            </div>
            Continue with {ProviderNames[provider]}
        </Button>
    )
}

export function SocialLoginButtons({ title, caption, ...props }: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (
        !preflight?.available_social_auth_providers ||
        !Object.values(preflight.available_social_auth_providers).filter((val) => !!val).length
    ) {
        return null
    }

    return (
        <div className="social-logins">
            {title && <h3 className="l3">{title}</h3>}
            {caption && <div className="caption">{caption}</div>}
            {Object.values(SocialAuthProviders).map((provider) => (
                <div key={provider}>
                    <SocialLoginButton provider={provider} {...props} />
                </div>
            ))}
        </div>
    )
}

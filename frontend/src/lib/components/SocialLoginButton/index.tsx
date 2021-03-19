import { Button } from 'antd'
import { useValues } from 'kea'
import React, { useMemo } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './index.scss'
import { GoogleOutlined, GithubOutlined, GitlabOutlined } from '@ant-design/icons'

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
    displayStyle?: 'button' | 'link'
}

export function SocialLoginButton({ provider, queryString }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <div>
            <Button className={`btn-social-login ${provider}`} href={`/login/${provider}/${queryString || ''}`}>
                <div className="btn-social-icon">
                    <div className="img" />
                </div>
                Continue with {ProviderNames[provider]}
            </Button>
        </div>
    )
}

export function SocialLoginLink({ provider, queryString }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    const icon = useMemo(() => {
        if (provider === SocialAuthProviders.Google) {
            return <GoogleOutlined />
        } else if (provider === SocialAuthProviders.GitHub) {
            return <GithubOutlined />
        } else if (provider === SocialAuthProviders.GitLab) {
            return <GitlabOutlined />
        }
    }, [provider])

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <Button
            className={`link-social-login ${provider}`}
            href={`/login/${provider}/${queryString || ''}`}
            icon={icon}
            type="link"
        >
            <span>{ProviderNames[provider]}</span>
        </Button>
    )
}

export function SocialLoginButtons({
    title,
    caption,
    displayStyle = 'button',
    ...props
}: SocialLoginButtonsProps): JSX.Element | null {
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
                <React.Fragment key={provider}>
                    {displayStyle === 'button' ? (
                        <SocialLoginButton provider={provider} {...props} />
                    ) : (
                        <SocialLoginLink provider={provider} {...props} />
                    )}
                </React.Fragment>
            ))}
        </div>
    )
}

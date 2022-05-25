import { Button } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import './index.scss'
import clsx from 'clsx'
import { SocialLoginIcon } from './SocialLoginIcon'
import { SSOProviders } from '~/types'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

interface SharedProps {
    queryString?: string
}

interface SocialLoginButtonProps extends SharedProps {
    provider: SSOProviders
}

interface SocialLoginButtonsProps extends SharedProps {
    title?: string
    caption?: string
    displayStyle?: 'button' | 'link'
}

export function SocialLoginLink({ provider, queryString }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    // SAML-based login requires an extra param as technically we can support multiple SAML backends
    const extraParam = provider === 'saml' ? (queryString ? '&idp=posthog_custom' : '?idp=posthog_custom') : ''

    return (
        <Button
            className={`link-social-login ${provider}`}
            href={`/login/${provider}/${queryString || ''}${extraParam}`}
            icon={SocialLoginIcon(provider)}
            type="link"
        >
            <span>{SSO_PROVIDER_NAMES[provider]}</span>
        </Button>
    )
}

export function SocialLoginButtons({ title, caption, ...props }: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    console.log('XX', preflight)
    if (
        !preflight?.available_social_auth_providers ||
        !Object.values(preflight.available_social_auth_providers).filter((val) => !!val).length
    ) {
        return null
    }

    return (
        <div
            className={clsx('social-logins', {
                empty: !Object.values(preflight.available_social_auth_providers).filter((v) => v).length,
            })}
        >
            {title && <h3 className="l3">{title}</h3>}
            {caption && <div className="caption">{caption}</div>}
            {Object.keys(preflight.available_social_auth_providers).map((provider) => (
                <SocialLoginLink key={provider} provider={provider as SSOProviders} {...props} />
            ))}
        </div>
    )
}

import { useValues } from 'kea'
import React from 'react'
import './index.scss'
import clsx from 'clsx'
import { SocialLoginIcon } from './SocialLoginIcon'
import { SSOProviders } from '~/types'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonButton } from '../LemonButton'

interface SharedProps {
    queryString?: string
}

interface SocialLoginButtonProps extends SharedProps {
    provider: SSOProviders
}

interface SocialLoginButtonsProps extends SharedProps {
    title?: string
    caption?: string
    className?: string
}

export function SocialLoginLink({ provider, queryString }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    // SAML-based login requires an extra param as technically we can support multiple SAML backends
    const extraParam = provider === 'saml' ? (queryString ? '&idp=posthog_custom' : '?idp=posthog_custom') : ''

    return (
        <LemonButton
            size="small"
            href={`/login/${provider}/${queryString || ''}${extraParam}`}
            icon={SocialLoginIcon(provider)}
        >
            <span>{SSO_PROVIDER_NAMES[provider]}</span>
        </LemonButton>
    )
}

export function SocialLoginButtons({
    title,
    caption,
    className,
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
        <div className={clsx(className, 'text-center space-y-2')}>
            {title && <h3>{title}</h3>}
            {caption && <span className="text-muted">{caption}</span>}
            <div className="flex gap-2 justify-center flex-wrap">
                {Object.keys(preflight.available_social_auth_providers).map((provider) => (
                    <SocialLoginLink key={provider} provider={provider as SSOProviders} {...props} />
                ))}
            </div>
        </div>
    )
}

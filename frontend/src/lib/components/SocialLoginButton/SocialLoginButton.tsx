import clsx from 'clsx'
import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { LoginMethod, SSOProvider } from '~/types'

import { SocialLoginIcon } from './SocialLoginIcon'

interface SocialLoginLinkProps {
    provider: SSOProvider
    extraQueryParams?: Record<string, string>
    children: JSX.Element
}

function SocialLoginLink({ provider, extraQueryParams, children }: SocialLoginLinkProps): JSX.Element {
    const { searchParams } = useValues(router)

    const loginParams: Record<string, string> = { ...extraQueryParams }
    if (searchParams.next) {
        loginParams.next = searchParams.next
    }
    if (provider === 'saml') {
        // SAML-based login requires an extra param as technically we can support multiple SAML backends
        loginParams.idp = 'posthog_custom'
    }
    const loginUrl = combineUrl(`/login/${provider}/`, loginParams).url
    const iframed = window !== window.parent

    return (
        // eslint-disable-next-line react/forbid-elements
        <a className="block" href={loginUrl} {...(iframed ? { target: '_blank', rel: 'noopener' } : {})}>
            {children}
        </a>
    )
}

interface SocialLoginButtonProps {
    provider: SSOProvider
    extraQueryParams?: Record<string, string>
    isLastUsed?: boolean
}

export function SocialLoginButton({
    provider,
    extraQueryParams,
    isLastUsed,
}: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <SocialLoginLink provider={provider} extraQueryParams={extraQueryParams}>
            <LemonButton
                size="medium"
                icon={<SocialLoginIcon provider={provider} />}
                active={isLastUsed}
                className="py-1 relative"
            >
                <span className="text-text-3000">{SSO_PROVIDER_NAMES[provider]}</span>
                {isLastUsed && (
                    <LemonTag
                        type="muted"
                        size="small"
                        className="absolute -top-3 left-1/2 -translate-x-1/2 pointer-events-none"
                    >
                        Last used
                    </LemonTag>
                )}
            </LemonButton>
        </SocialLoginLink>
    )
}

interface SocialLoginButtonsProps {
    title?: string
    caption?: string
    captionLocation?: 'top' | 'bottom'
    className?: string
    topDivider?: boolean
    bottomDivider?: boolean
    extraQueryParams?: Record<string, string>
    lastUsedProvider?: LoginMethod
}

export function SocialLoginButtons({
    title,
    caption,
    captionLocation = 'top',
    className,
    topDivider,
    bottomDivider,
    lastUsedProvider,
    ...props
}: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight, socialAuthAvailable } = useValues(preflightLogic)

    if (!preflight || !socialAuthAvailable) {
        return null
    }

    const order: string[] = Object.keys(SSO_PROVIDER_NAMES)

    return (
        <>
            {topDivider ? <LemonDivider dashed className="my-4" /> : null}

            <div className={clsx(className, 'text-center deprecated-space-y-4')}>
                {title && <h3>{title}</h3>}
                {caption && captionLocation === 'top' && <p className="text-secondary">{caption}</p>}
                <div className="flex gap-2 justify-center flex-wrap">
                    {Object.keys(preflight.available_social_auth_providers)
                        .sort((a, b) => order.indexOf(a) - order.indexOf(b))
                        .map((provider) => (
                            <SocialLoginButton
                                key={provider}
                                provider={provider as SSOProvider}
                                isLastUsed={lastUsedProvider === provider}
                                {...props}
                            />
                        ))}
                </div>
                {caption && captionLocation === 'bottom' && <p className="text-secondary">{caption}</p>}
            </div>
            {bottomDivider ? <LemonDivider dashed className="my-6" /> : null}
        </>
    )
}

type SSOEnforcedLoginButtonProps = SocialLoginButtonProps &
    Partial<LemonButtonWithoutSideActionProps> & {
        email: string
    } & {
        actionText?: string
    }

export function SSOEnforcedLoginButton({
    provider,
    email,
    extraQueryParams,
    actionText = 'Log in',
    isLastUsed,
    ...props
}: SSOEnforcedLoginButtonProps): JSX.Element {
    return (
        <SocialLoginLink provider={provider} extraQueryParams={{ ...extraQueryParams, email }}>
            <LemonButton
                className="btn-bridge relative"
                data-attr="sso-login"
                htmlType="button"
                type="secondary"
                fullWidth
                center
                icon={<SocialLoginIcon provider={provider} />}
                size="large"
                {...props}
            >
                {actionText} with {SSO_PROVIDER_NAMES[provider]}
                {isLastUsed && (
                    <LemonTag type="muted" size="medium" className="absolute -top-3 -right-2 pointer-events-none">
                        Last used
                    </LemonTag>
                )}
            </LemonButton>
        </SocialLoginLink>
    )
}

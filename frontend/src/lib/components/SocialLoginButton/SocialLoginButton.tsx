import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { BeginPasskeyLoginParams, passkeyLogic } from 'scenes/authentication/passkeyLogic'

import { LoginMethod, SSOProvider } from '~/types'

import { SocialLoginIcon } from './SocialLoginIcon'
import passkeyLogo from './passkey.svg'

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
            <div className="relative">
                <LemonButton
                    size="large"
                    icon={<SocialLoginIcon provider={provider} />}
                    active={isLastUsed}
                    tooltip={SSO_PROVIDER_NAMES[provider]}
                />
                {isLastUsed && (
                    <LemonTag
                        type="muted"
                        size="small"
                        className="absolute -top-3 left-1/2 -translate-x-1/2 pointer-events-none"
                    >
                        Last used
                    </LemonTag>
                )}
            </div>
        </SocialLoginLink>
    )
}

interface PasskeyLoginButtonProps {
    isLastUsed?: boolean
    extraQueryParams?: Record<string, string>
}

export function PasskeyLoginButton({ isLastUsed, extraQueryParams }: PasskeyLoginButtonProps): JSX.Element {
    const { beginPasskeyLogin } = useActions(passkeyLogic)
    const { isLoading } = useValues(passkeyLogic)

    const {
        reauth,
    }: {
        reauth?: 'true'
    } = extraQueryParams ?? {}

    return (
        <div className="relative">
            <LemonButton
                size="large"
                icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
                active={isLastUsed}
                className={clsx(!isLastUsed && reauth !== 'true' && 'bg-mark')}
                tooltip="Passkey"
                htmlType="button"
                onClick={() => {
                    beginPasskeyLogin(undefined, extraQueryParams as BeginPasskeyLoginParams)
                }}
                loading={isLoading}
                data-attr="passkey-login"
            />
            {reauth !== 'true' && (
                <LemonTag
                    type="muted"
                    size="small"
                    className="absolute -top-3 left-1/2 -translate-x-1/2 pointer-events-none"
                >
                    {isLastUsed ? 'Last used' : 'New'}
                </LemonTag>
            )}
        </div>
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
    showPasskey?: boolean
}

export function SocialLoginButtons({
    title,
    caption,
    captionLocation = 'top',
    className,
    topDivider,
    bottomDivider,
    lastUsedProvider,
    showPasskey = false,
    ...props
}: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight, socialAuthAvailable } = useValues(preflightLogic)

    if (!preflight || (!socialAuthAvailable && !showPasskey)) {
        return null
    }

    const order: string[] = Object.keys(SSO_PROVIDER_NAMES)
    const socialProviders = socialAuthAvailable
        ? Object.keys(preflight.available_social_auth_providers).sort((a, b) => order.indexOf(a) - order.indexOf(b))
        : []

    return (
        <>
            {topDivider ? <LemonDivider dashed className="my-4" /> : null}

            <div className={clsx(className, 'text-center deprecated-space-y-4')}>
                {title && <h3>{title}</h3>}
                {caption && captionLocation === 'top' && <p className="text-secondary">{caption}</p>}
                <div className="flex gap-4 justify-center flex-wrap">
                    {socialProviders.map((provider) => (
                        <SocialLoginButton
                            key={provider}
                            provider={provider as SSOProvider}
                            isLastUsed={lastUsedProvider === provider}
                            {...props}
                        />
                    ))}
                    {showPasskey && <PasskeyLoginButton isLastUsed={lastUsedProvider === 'passkey'} {...props} />}
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

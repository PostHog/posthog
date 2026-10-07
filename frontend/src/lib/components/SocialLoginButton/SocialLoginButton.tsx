import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { BeginPasskeyLoginParams, passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { SSOProvider } from '~/types'

import passkeyLogo from './passkey.svg'
import { SocialLoginIcon } from './SocialLoginIcon'
import { getSocialLoginUrl } from './socialLoginUrl'

interface SocialLoginLinkProps {
    provider: SSOProvider
    extraQueryParams?: Record<string, string>
    onProviderClick?: (provider: SSOProvider) => void
    children: JSX.Element
}

function SocialLoginLink({ provider, extraQueryParams, onProviderClick, children }: SocialLoginLinkProps): JSX.Element {
    const { searchParams } = useValues(router)

    const loginUrl = getSocialLoginUrl(provider, extraQueryParams, searchParams)
    const iframed = window !== window.parent

    return (
        // eslint-disable-next-line react/forbid-elements
        <a
            className="block"
            href={loginUrl}
            onClick={
                onProviderClick
                    ? (event) => {
                          event.preventDefault()
                          onProviderClick(provider)
                      }
                    : undefined
            }
            {...(iframed && !onProviderClick ? { target: '_blank', rel: 'noopener' } : {})}
        >
            {children}
        </a>
    )
}

interface SocialLoginButtonProps {
    provider: SSOProvider
    extraQueryParams?: Record<string, string>
    onProviderClick?: (provider: SSOProvider) => void
}

export function SocialLoginButton({
    provider,
    extraQueryParams,
    onProviderClick,
}: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <SocialLoginLink provider={provider} extraQueryParams={extraQueryParams} onProviderClick={onProviderClick}>
            <LemonButton
                size="large"
                icon={<SocialLoginIcon provider={provider} />}
                tooltip={SSO_PROVIDER_NAMES[provider]}
            />
        </SocialLoginLink>
    )
}

interface PasskeyLoginButtonProps {
    extraQueryParams?: Record<string, string>
}

export function PasskeyLoginButton({ extraQueryParams }: PasskeyLoginButtonProps): JSX.Element {
    const { beginPasskeyLogin } = useActions(passkeyLogic)
    const { isLoading } = useValues(passkeyLogic)

    return (
        <LemonButton
            size="large"
            icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
            tooltip="Passkey"
            htmlType="button"
            onClick={() => {
                beginPasskeyLogin(undefined, extraQueryParams as BeginPasskeyLoginParams)
            }}
            loading={isLoading}
            data-attr="passkey-login"
        />
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
    onProviderClick?: (provider: SSOProvider) => void
    showPasskey?: boolean
    /**
     * Limit the rendered providers to this allowlist. Used when we know which providers a specific
     * account can actually use, so we don't offer a button that would fail. `null`/omitted means
     * "no restriction" — render everything the instance has configured.
     *
     * Note `'saml'` is never rendered here (it isn't in `available_social_auth_providers`); it goes
     * through `SSOEnforcedLoginButton` instead.
     */
    restrictToProviders?: SSOProvider[] | null
}

export function SocialLoginButtons({
    title,
    caption,
    captionLocation = 'top',
    className,
    topDivider,
    bottomDivider,
    showPasskey = false,
    restrictToProviders,
    onProviderClick,
    ...props
}: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight, socialAuthAvailable } = useValues(preflightLogic)

    if (!preflight || (!socialAuthAvailable && !showPasskey)) {
        return null
    }

    const order: string[] = Object.keys(SSO_PROVIDER_NAMES)
    const socialProviders = socialAuthAvailable
        ? Object.keys(preflight.available_social_auth_providers)
              .filter((provider) => !restrictToProviders || restrictToProviders.includes(provider as SSOProvider))
              .sort((a, b) => order.indexOf(a) - order.indexOf(b))
        : []

    if (!socialProviders.length && !showPasskey) {
        return null
    }

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
                            onProviderClick={onProviderClick}
                            {...props}
                        />
                    ))}
                    {showPasskey && <PasskeyLoginButton {...props} />}
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
    onProviderClick,
    actionText = 'Log in',
    ...props
}: SSOEnforcedLoginButtonProps): JSX.Element {
    return (
        <SocialLoginLink
            provider={provider}
            extraQueryParams={{ ...extraQueryParams, email }}
            onProviderClick={onProviderClick}
        >
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
            </LemonButton>
        </SocialLoginLink>
    )
}

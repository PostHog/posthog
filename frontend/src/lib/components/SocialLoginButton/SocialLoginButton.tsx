import { useValues } from 'kea'
import clsx from 'clsx'
import { SocialLoginIcon } from './SocialLoginIcon'
import { SSOProvider } from '~/types'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { router, combineUrl } from 'kea-router'

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

    return (
        // eslint-disable-next-line react/forbid-elements
        <a className="block" href={loginUrl}>
            {children}
        </a>
    )
}

interface SocialLoginButtonProps {
    provider: SSOProvider
    redirectQueryParams?: Record<string, string>
}

export function SocialLoginButton({ provider, redirectQueryParams }: SocialLoginButtonProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.available_social_auth_providers[provider]) {
        return null
    }

    return (
        <SocialLoginLink provider={provider} extraQueryParams={redirectQueryParams}>
            <LemonButton size="medium" icon={SocialLoginIcon(provider)}>
                <span className={'text-default'}>{SSO_PROVIDER_NAMES[provider]}</span>
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
    redirectQueryParams?: Record<string, string>
}

export function SocialLoginButtons({
    title,
    caption,
    captionLocation = 'top',
    className,
    topDivider,
    bottomDivider,
    ...props
}: SocialLoginButtonsProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    const order: string[] = Object.keys(SSO_PROVIDER_NAMES)

    if (
        !preflight?.available_social_auth_providers ||
        !Object.values(preflight.available_social_auth_providers).filter((val) => !!val).length
    ) {
        return null
    }

    return (
        <>
            {topDivider ? <LemonDivider dashed className="my-4" /> : null}

            <div className={clsx(className, 'text-center space-y-4')}>
                {title && <h3>{title}</h3>}
                {caption && captionLocation === 'top' && <p className="text-muted">{caption}</p>}
                <div className="flex gap-2 justify-center flex-wrap">
                    {Object.keys(preflight.available_social_auth_providers)
                        .sort((a, b) => order.indexOf(a) - order.indexOf(b))
                        .map((provider) => (
                            <SocialLoginButton key={provider} provider={provider as SSOProvider} {...props} />
                        ))}
                </div>
                {caption && captionLocation === 'bottom' && <p className="text-muted">{caption}</p>}
            </div>
            {bottomDivider ? <LemonDivider dashed className="my-6" /> : null}
        </>
    )
}

interface SSOEnforcedLoginButtonProps {
    provider: SSOProvider
    email: string
}

export function SSOEnforcedLoginButton({ provider, email }: SSOEnforcedLoginButtonProps): JSX.Element {
    return (
        <SocialLoginLink provider={provider} extraQueryParams={{ email }}>
            <LemonButton
                className="btn-bridge"
                data-attr="sso-login"
                htmlType="button"
                type="secondary"
                fullWidth
                center
                icon={SocialLoginIcon(provider)}
            >
                Log in with {SSO_PROVIDER_NAMES[provider]}
            </LemonButton>
        </SocialLoginLink>
    )
}

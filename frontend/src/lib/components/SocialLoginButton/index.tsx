import { useValues } from 'kea'
import './index.scss'
import clsx from 'clsx'
import { SocialLoginIcon } from './SocialLoginIcon'
import { SSOProviders } from '~/types'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonButton } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
import { router } from 'kea-router'

interface SharedProps {
    queryString?: string
}

interface SocialLoginButtonProps extends SharedProps {
    provider: SSOProviders
}

interface SocialLoginButtonsProps extends SharedProps {
    title?: string
    caption?: string
    captionLocation?: 'top' | 'bottom'
    className?: string
    topDivider?: boolean
    bottomDivider?: boolean
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
            size="medium"
            to={`/login/${provider}/${queryString || ''}${extraParam}`}
            disableClientSideRouting
            icon={SocialLoginIcon(provider)}
        >
            <span className={'text-default'}>{SSO_PROVIDER_NAMES[provider]}</span>
        </LemonButton>
    )
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

    const { searchParams } = useValues(router)

    const loginQueryParams = searchParams?.next ? `?next=${searchParams.next}` : undefined

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
                            <SocialLoginLink
                                queryString={loginQueryParams}
                                key={provider}
                                provider={provider as SSOProviders}
                                {...props}
                            />
                        ))}
                </div>
                {caption && captionLocation === 'bottom' && <p className="text-muted">{caption}</p>}
            </div>
            {bottomDivider ? <LemonDivider dashed className="my-6" /> : null}
        </>
    )
}

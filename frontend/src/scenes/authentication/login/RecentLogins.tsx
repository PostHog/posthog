import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { RecentLogin } from 'scenes/authentication/shared/recentLogins'

import { LoginMethod } from '~/types'

import { recentLoginsLogic } from './recentLoginsLogic'

function methodLabel(method: LoginMethod): string | null {
    if (method === 'password') {
        return 'Password'
    }
    if (method === 'passkey') {
        return 'Passkey'
    }
    return method ? SSO_PROVIDER_NAMES[method] : null
}

function RecentLoginIcon({ method }: { method: LoginMethod }): JSX.Element {
    if (method === 'passkey') {
        return <img src={passkeyLogo} alt="" className="object-contain w-5 h-5" />
    }
    if (method && method !== 'password') {
        return <SocialLoginIcon provider={method} />
    }
    return <IconLock />
}

export function RecentLogins({ onSelect }: { onSelect?: (recentLogin: RecentLogin) => void }): JSX.Element | null {
    const { recentLogins } = useValues(recentLoginsLogic)
    const { selectRecentLogin } = useActions(recentLoginsLogic)

    if (!recentLogins.length) {
        return null
    }

    return (
        <>
            <LemonDivider dashed className="my-4" />
            {/* ph-no-capture keeps the email addresses out of autocapture and session replay */}
            <div className="ph-no-capture flex flex-col gap-2">
                <p className="text-secondary text-center mb-1">Recent logins</p>
                {recentLogins.map((recentLogin, index) => {
                    const label = methodLabel(recentLogin.method)
                    const lastUsed = dayjs(recentLogin.lastUsedAt).fromNow()
                    return (
                        <LemonButton
                            key={recentLogin.email}
                            type="secondary"
                            size="large"
                            fullWidth
                            icon={<RecentLoginIcon method={recentLogin.method} />}
                            data-attr="login-recent-account"
                            onClick={() => {
                                selectRecentLogin(recentLogin)
                                onSelect?.(recentLogin)
                            }}
                        >
                            <span className="flex items-center gap-2 min-w-0 flex-1">
                                <span className="flex flex-col min-w-0 flex-1 text-left">
                                    <span className="font-semibold truncate">{recentLogin.email}</span>
                                    <span className="text-xs font-normal text-secondary truncate">
                                        {label ? `${label} · ${lastUsed}` : lastUsed}
                                    </span>
                                </span>
                                {index === 0 && <LemonTag type="success">Latest</LemonTag>}
                            </span>
                        </LemonButton>
                    )
                })}
            </div>
        </>
    )
}

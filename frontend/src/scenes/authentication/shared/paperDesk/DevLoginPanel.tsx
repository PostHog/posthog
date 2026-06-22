import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconTerminal } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { OAUTH_REGIONS } from 'lib/oauth/oauthClient'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

import { devLoginLogic } from '../devLoginLogic'

/** Floating dev-only panel (bottom-left) combining dev-login shortcuts and OAuth prod-data login. */
export function DevLoginPanel(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { devUsers, devUsersLoading, devLoginTimeSavedLabel } = useValues(devLoginLogic)
    const { devLogin, loadDevUsers } = useActions(devLoginLogic)
    const { loginInProgress } = useValues(oauthLogic)
    const { beginLogin } = useActions(oauthLogic)
    const [open, setOpen] = useState(false)

    const isDebug = !!preflight?.is_debug
    const allowDevLogin = !!preflight?.allow_dev_login

    useEffect(() => {
        if (allowDevLogin) {
            loadDevUsers(null)
        }
    }, [allowDevLogin, loadDevUsers])

    if (!isDebug) {
        return null
    }

    const showDevLogin = allowDevLogin && !devUsersLoading && devUsers.length > 0

    return (
        <div className="fixed bottom-4 left-4 z-50">
            {open ? (
                <div className="w-72 bg-white border border-[#e0e1d9] rounded-lg shadow-[0_20px_44px_-26px_rgb(40_38_30/35%),0_3px_0_#e0e1d9] overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-dashed border-[#e0e1d9] bg-[#fbfbf9]">
                        <span className="font-mono text-xs font-semibold text-primary/50">// dev tools</span>
                        <button
                            type="button"
                            className="text-secondary hover:text-primary text-sm leading-none"
                            onClick={() => setOpen(false)}
                            aria-label="Close dev tools"
                        >
                            ✕
                        </button>
                    </div>
                    {showDevLogin && (
                        <div className="px-4 py-3 border-b border-dashed border-[#e0e1d9]">
                            <p className="font-mono text-xs text-primary/50 mb-2">// dev login</p>
                            <div className="flex flex-col gap-1">
                                {devUsers.map((u) => (
                                    <LemonButton
                                        key={u.email}
                                        size="small"
                                        type="tertiary"
                                        fullWidth
                                        onClick={() => devLogin(u.email)}
                                        data-attr={`dev-login-${u.email}`}
                                    >
                                        <span className="flex items-center gap-2 w-full">
                                            <span className="flex-1 text-left truncate text-xs">{u.email}</span>
                                            {u.label && (
                                                <LemonTag type="success" size="small">
                                                    {u.label}
                                                </LemonTag>
                                            )}
                                            {u.is_staff && !u.label && (
                                                <LemonTag type="default" size="small">
                                                    Staff
                                                </LemonTag>
                                            )}
                                        </span>
                                    </LemonButton>
                                ))}
                            </div>
                            {devLoginTimeSavedLabel && (
                                <p className="mt-2 text-xs text-secondary">{devLoginTimeSavedLabel}</p>
                            )}
                        </div>
                    )}
                    <div className="px-4 py-3">
                        <p className="font-mono text-xs text-primary/50 mb-2">// prod data via OAuth</p>
                        <div className="flex flex-col gap-1.5">
                            <LemonButton
                                size="small"
                                type="secondary"
                                fullWidth
                                center
                                disabled={loginInProgress}
                                loading={loginInProgress}
                                onClick={() => beginLogin(Region.US)}
                                data-attr="dev-oauth-us"
                            >
                                <span className="flex items-center gap-2">
                                    <span className="text-base leading-none">{OAUTH_REGIONS[Region.US].flag}</span>
                                    US Cloud
                                </span>
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                fullWidth
                                center
                                disabled={loginInProgress}
                                loading={loginInProgress}
                                onClick={() => beginLogin(Region.EU)}
                                data-attr="dev-oauth-eu"
                            >
                                <span className="flex items-center gap-2">
                                    <span className="text-base leading-none">{OAUTH_REGIONS[Region.EU].flag}</span>
                                    EU Cloud
                                </span>
                            </LemonButton>
                        </div>
                    </div>
                </div>
            ) : (
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-[#e0e1d9] rounded-full shadow-sm text-xs font-semibold text-primary/50 hover:text-primary hover:border-accent transition-colors"
                >
                    <IconTerminal className="w-3.5 h-3.5" />
                    Dev tools
                </button>
            )}
        </div>
    )
}

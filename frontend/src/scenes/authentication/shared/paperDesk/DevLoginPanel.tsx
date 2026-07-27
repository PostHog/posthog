import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { OAUTH_REGIONS } from 'lib/oauth/oauthClient'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

import { devLoginLogic } from '../devLoginLogic'

/** Floating dev-only panel (top-right) combining dev-login shortcuts and OAuth prod-data login. */
export function DevLoginPanel(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { devUsers, devUsersLoading } = useValues(devLoginLogic)
    const { devLogin, loadDevUsers } = useActions(devLoginLogic)
    const { loginInProgress } = useValues(oauthLogic)
    const { beginLogin } = useActions(oauthLogic)
    const [open, setOpen] = useState(true)

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
        <div className="fixed top-4 right-4 z-50">
            {open ? (
                <div className="w-64 bg-white border rounded shadow p-3">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-semibold text-muted">Login tools</span>
                        <button type="button" className="text-muted" onClick={() => setOpen(false)} aria-label="Close">
                            ✕
                        </button>
                    </div>
                    {showDevLogin && (
                        <div className="mb-4">
                            <p className="text-xs font-medium text-muted mb-1.5">Login as</p>
                            <div className="flex flex-col gap-1">
                                {devUsers.map((u) => (
                                    <button
                                        key={u.email}
                                        type="button"
                                        onClick={() => devLogin(u.email)}
                                        data-attr={`dev-login-${u.email}`}
                                        className="flex items-center gap-2 w-full text-left px-2.5 py-1.5 rounded border border-border bg-bg-light hover:border-accent hover:bg-accent-highlight transition-colors"
                                    >
                                        <span className="flex-1 truncate text-xs">{u.email}</span>
                                        {u.label && <span className="text-xs text-muted">{u.label}</span>}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                    {showDevLogin && <div className="border-t border-border my-3" />}
                    <div>
                        <p className="text-xs font-medium text-muted mb-1.5">Login via OAuth</p>
                        <div className="flex flex-col gap-1">
                            <button
                                type="button"
                                disabled={loginInProgress}
                                onClick={() => beginLogin(Region.US)}
                                data-attr="dev-oauth-us"
                                className="flex items-center gap-2 w-full text-left px-2.5 py-1.5 rounded border border-border bg-bg-light hover:border-accent hover:bg-accent-highlight disabled:opacity-50 disabled:hover:border-border disabled:hover:bg-bg-light transition-colors"
                            >
                                <span className="text-base leading-none">{OAUTH_REGIONS[Region.US].flag}</span>
                                <span className="text-xs">US Cloud</span>
                            </button>
                            <button
                                type="button"
                                disabled={loginInProgress}
                                onClick={() => beginLogin(Region.EU)}
                                data-attr="dev-oauth-eu"
                                className="flex items-center gap-2 w-full text-left px-2.5 py-1.5 rounded border border-border bg-bg-light hover:border-accent hover:bg-accent-highlight disabled:opacity-50 disabled:hover:border-border disabled:hover:bg-bg-light transition-colors"
                            >
                                <span className="text-base leading-none">{OAUTH_REGIONS[Region.EU].flag}</span>
                                <span className="text-xs">EU Cloud</span>
                            </button>
                        </div>
                    </div>
                </div>
            ) : (
                <LemonButton size="small" type="tertiary" onClick={() => setOpen(true)}>
                    Login tools
                </LemonButton>
            )}
        </div>
    )
}

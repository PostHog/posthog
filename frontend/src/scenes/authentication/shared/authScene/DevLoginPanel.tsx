import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlus, IconX } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { OAUTH_REGIONS } from 'lib/oauth/oauthClient'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { hashCodeForString } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

import { DevUser, devLoginLogic } from '../devLoginLogic'

/** Floating dev-only panel (top-right) combining dev-login shortcuts and OAuth prod-data login. */
export function DevLoginPanel(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { devUsers, devUsersLoading, devLoginPanelOpen, createFreshAccountLoading } = useValues(devLoginLogic)
    const { devLogin, loadDevUsers, createFreshAccount, setDevLoginPanelOpen } = useActions(devLoginLogic)
    const { loginInProgress } = useValues(oauthLogic)
    const { beginLogin } = useActions(oauthLogic)

    const isDebug = !!preflight?.is_debug
    const allowDevLogin = !!preflight?.allow_dev_login

    useEffect(() => {
        if (allowDevLogin && devLoginPanelOpen) {
            loadDevUsers(null)
        }
    }, [allowDevLogin, devLoginPanelOpen, loadDevUsers])

    if (!isDebug) {
        return null
    }

    if (!devLoginPanelOpen) {
        return (
            <div className="fixed top-4 right-4 z-50">
                <LemonButton size="small" type="tertiary" onClick={() => setDevLoginPanelOpen(true)}>
                    Login tools
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="AuthScene__card fixed top-4 right-4 z-50 flex flex-col w-72 max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)]">
            <div className="flex items-center justify-between gap-2 pl-3 pr-1.5 py-1.5 border-b border-[#e0e1d9]">
                <span className="text-xs font-semibold text-muted">Login tools</span>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={() => setDevLoginPanelOpen(false)}
                    tooltip="Hide login tools"
                    aria-label="Hide login tools"
                />
            </div>
            {allowDevLogin && (
                <div className="flex-1 min-h-0 max-h-[45vh] overflow-y-auto p-1.5">
                    {devUsers.map((user) => (
                        <DevUserButton key={user.email} user={user} onClick={devLogin} />
                    ))}
                    {devUsersLoading && (
                        <div className="flex justify-center py-4">
                            <Spinner />
                        </div>
                    )}
                    {!devUsersLoading && devUsers.length === 0 && (
                        <p className="text-xs text-muted text-center px-2 py-4 m-0">
                            No accounts yet. Create a fresh demo account below.
                        </p>
                    )}
                </div>
            )}
            <div className="flex flex-col gap-2 px-3 py-2.5 border-t border-[#e0e1d9]">
                {allowDevLogin && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        center
                        icon={<IconPlus />}
                        loading={createFreshAccountLoading}
                        disabledReason={createFreshAccountLoading ? 'Creating account' : undefined}
                        onClick={createFreshAccount}
                        data-attr="dev-create-fresh-account"
                        tooltip="Creates a throwaway account and organization with a random name and the password 12345678, then opens onboarding."
                    >
                        Create fresh demo account
                    </LemonButton>
                )}
                <div>
                    <p className="text-xs font-medium text-muted mb-1">Log in via OAuth</p>
                    <div className="grid grid-cols-2 gap-1">
                        {([Region.US, Region.EU] as const).map((region) => (
                            <LemonButton
                                key={region}
                                type="secondary"
                                size="small"
                                fullWidth
                                center
                                disabledReason={loginInProgress ? 'Login in progress' : undefined}
                                onClick={() => beginLogin(region)}
                                data-attr={`dev-oauth-${region.toLowerCase()}`}
                                icon={<span className="text-base leading-none">{OAUTH_REGIONS[region].flag}</span>}
                            >
                                {region === Region.US ? 'US Cloud' : 'EU Cloud'}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

function DevUserButton({ user, onClick }: { user: DevUser; onClick: (email: string) => void }): JSX.Element {
    const subtitle = user.label || (user.is_staff ? 'Staff' : user.first_name)
    // Color the lettermark off the email rather than list position, so an account keeps the same
    // one as the list reorders by recency.
    const colorIndex = hashCodeForString(user.email)
    return (
        <LemonButton
            size="small"
            fullWidth
            onClick={() => onClick(user.email)}
            data-attr={`dev-login-${user.email}`}
            icon={<Lettermark name={user.first_name || user.email} index={colorIndex} size="small" rounded />}
            sideIcon={
                user.last_login ? (
                    <span className="text-xs text-muted whitespace-nowrap">{dayjs(user.last_login).fromNow(true)}</span>
                ) : undefined
            }
            tooltip={user.email}
        >
            <span className="flex flex-col min-w-0 py-0.5">
                <span className="text-xs truncate">{user.email}</span>
                {subtitle && <span className="text-xs text-muted truncate font-normal">{subtitle}</span>}
            </span>
        </LemonButton>
    )
}

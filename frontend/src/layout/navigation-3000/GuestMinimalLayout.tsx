import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import IconPostHog from 'public/posthog-icon.svg'

/**
 * Stripped-down app shell used whenever the current user is a guest.
 *
 * There's no sidebar, project picker, search, or Max — guests only see:
 * the PostHog mark, a link back to their grants landing, their email, and
 * a logout button.
 */
export function GuestMinimalLayout({ children }: { children: React.ReactNode }): JSX.Element {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)

    return (
        <div className="flex flex-col h-screen">
            <header className="flex items-center justify-between px-4 py-2 border-b bg-bg-light">
                <div className="flex items-center gap-3">
                    <img src={IconPostHog} alt="PostHog" className="h-6 w-6" />
                    <span className="text-sm font-medium text-muted">Guest access</span>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton type="tertiary" size="small" to={urls.guest()}>
                        Shared with you
                    </LemonButton>
                    <span className="text-sm text-muted ph-no-capture">{user?.email}</span>
                    {/* Logout is a backend endpoint at `/logout`, not a SPA scene — going through
                     *  `userLogic.logout` resets PostHog analytics and then hard-navigates so the
                     *  Django session is actually cleared. Using `to="/logout"` would let the kea
                     *  router prepend `/project/<team>/`, producing a 404. */}
                    <LemonButton type="tertiary" size="small" onClick={() => logout()}>
                        Log out
                    </LemonButton>
                </div>
            </header>
            <main className="flex-1 overflow-auto p-4">{children}</main>
        </div>
    )
}

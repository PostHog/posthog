import { useValues } from 'kea'
import React from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

export function GuestMinimalLayout({ children }: { children: React.ReactNode }): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="flex flex-col h-screen">
            <header className="flex items-center justify-between px-4 py-2 border-b bg-bg-light">
                <div className="flex items-center gap-3">
                    <img src="/static/posthog-icon.svg" alt="PostHog" className="h-6 w-6" />
                    <span className="text-sm font-medium text-muted">Guest access</span>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton type="tertiary" size="small" to={urls.guest()}>
                        Your shared content
                    </LemonButton>
                    <span className="text-sm text-muted">{user?.email}</span>
                    <LemonButton type="tertiary" size="small" to="/logout">
                        Log out
                    </LemonButton>
                </div>
            </header>
            <main className="flex-1 overflow-auto">{children}</main>
        </div>
    )
}

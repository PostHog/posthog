import './AuthScene.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { type ReactNode } from 'react'

import { Logo } from 'lib/brand'
import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'
import { inStorybook } from 'lib/utils/dom'

import { pendingOAuthConnectionLogic } from '../pendingOAuthConnectionLogic'
import { type AuthNotes } from './authNotes'
import { AuthSceneBackdrop } from './AuthSceneBackdrop'
import { DevLoginPanel } from './DevLoginPanel'
import { Typewriter } from './Typewriter'

export function AuthScene({
    notes,
    wide = false,
    children,
}: {
    /** An entry from `AUTH_NOTES`. */
    notes: AuthNotes
    /** For a card that holds tables, such as the credential review. */
    wide?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <AuthSceneBackdrop className="relative h-screen overflow-x-hidden overflow-y-auto">
            <div className="hidden sm:block">
                <Typewriter lines={notes} />
            </div>
            <div className="relative z-[3] flex flex-col items-center justify-center min-h-full py-18 px-4 sm:px-10">
                <div
                    className={clsx(
                        'AuthScene__column flex flex-col items-center max-w-full',
                        wide ? 'w-[48rem]' : 'w-[27rem]'
                    )}
                >
                    {children}
                </div>
            </div>
            {/* The dev login panel is a local tool, so stories and their snapshots leave it out */}
            {!inStorybook() && <DevLoginPanel />}
        </AuthSceneBackdrop>
    )
}

/** Logo (or custom header) + white card + optional footer note — the column contents. */
export function AuthSceneCard({
    top,
    footer,
    showPendingConnection = false,
    children,
}: {
    top?: ReactNode
    footer?: ReactNode
    /**
     * Shows the pending OAuth app's logo in place of the PostHog logo. Set it only on screens on the way to
     * OAuth consent. The pending-connection cookie stays after a person abandons a connect, so on any other
     * screen the logo suggests that the action is for that app.
     */
    showPendingConnection?: boolean
    children: ReactNode
}): JSX.Element {
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    return (
        <>
            {top !== undefined ? (
                top
            ) : showPendingConnection && pendingConnection ? (
                <OAuthConnectionLogos appName={pendingConnection.clientName} logoUri={pendingConnection.logoUri} />
            ) : (
                <span className="AuthScene__logo block mb-4">
                    <Logo size="lg" />
                </span>
            )}
            <div className="AuthScene__card w-full pt-8 px-5 sm:px-9 pb-8">{children}</div>
            {footer}
        </>
    )
}

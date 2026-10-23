import './AuthScene.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { type ReactNode } from 'react'

import { Logo } from 'lib/brand'
import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'

import { pendingOAuthConnectionLogic } from '../pendingOAuthConnectionLogic'
import { AuthSceneBackdrop } from './AuthSceneBackdrop'
import { DevLoginPanel } from './DevLoginPanel'
import { Typewriter } from './Typewriter'

export function AuthScene({
    notes,
    wide = false,
    children,
}: {
    notes: string[]
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
            <DevLoginPanel />
        </AuthSceneBackdrop>
    )
}

/** Logo (or custom header) + white card + optional footer note — the column contents. */
export function AuthSceneCard({
    top,
    footer,
    children,
}: {
    top?: ReactNode
    footer?: ReactNode
    children: ReactNode
}): JSX.Element {
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    return (
        <>
            {top !== undefined ? (
                top
            ) : pendingConnection ? (
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

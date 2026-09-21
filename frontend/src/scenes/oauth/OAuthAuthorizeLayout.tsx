import { useValues } from 'kea'
import { type ReactNode } from 'react'

import { Logo } from 'lib/brand'
import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'
import { AuthSceneBackdrop } from 'scenes/authentication/shared/authScene/AuthSceneBackdrop'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

/**
 * Does not use `AuthScene`, because that scrolls the page. The consent card scrolls its own
 * permission list instead, so that the action row stays in view however many permissions an
 * application asks for.
 */
export function OAuthAuthorizeLayout({ children }: { children: ReactNode }): JSX.Element {
    const { oauthApplication, appName } = useValues(oauthAuthorizeLogic)

    return (
        <AuthSceneBackdrop className="flex flex-col h-full max-h-full overflow-hidden py-6 px-4 sm:px-6">
            <div className="flex flex-col min-h-0 w-full max-w-2xl mx-auto">
                {oauthApplication ? (
                    <OAuthConnectionLogos appName={appName} logoUri={oauthApplication.logo_uri ?? null} />
                ) : (
                    <span className="AuthScene__logo shrink-0 block mx-auto mb-4">
                        <Logo variant="gradient" size="lg" />
                    </span>
                )}
                {children}
            </div>
        </AuthSceneBackdrop>
    )
}

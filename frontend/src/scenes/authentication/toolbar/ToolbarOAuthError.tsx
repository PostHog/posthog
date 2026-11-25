import { IconWarning } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getAppContext } from 'lib/utils/getAppContext'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { ToolbarOAuthErrorContext } from '~/types'

export const scene: SceneExport = {
    component: ToolbarOAuthError,
}

// The server passes the error only once, so a reload or a direct visit shows this generic error.
const FALLBACK_ERROR: ToolbarOAuthErrorContext = {
    title: 'The toolbar could not open',
    message: 'Open the toolbar from your site again.',
    detail: null,
    links_to_authorized_urls: false,
}

export function ToolbarOAuthError(): JSX.Element {
    const error = getAppContext()?.toolbar_oauth_error ?? FALLBACK_ERROR
    // The app opens the toolbar in a new tab with noopener, and that tab has no previous page to go back to.
    const canGoBack = window.history.length > 1

    return (
        <AuthScene notes={AUTH_NOTES.toolbarOAuth.error}>
            <AuthSceneCard>
                <div className="flex justify-center mb-3">
                    <IconWarning className="text-danger text-5xl" />
                </div>
                <AuthCardTitle title={error.title} sub={error.message} />
                <div className="flex flex-col gap-3">
                    {error.detail && <AuthBanner variant="note">{error.detail}</AuthBanner>}
                    {error.links_to_authorized_urls && (
                        <LemonButton
                            fullWidth
                            type="primary"
                            center
                            size="large"
                            to={urls.settings('project-web-analytics', 'web-analytics-authorized-urls')}
                            data-attr="toolbar-oauth-error-project-settings"
                        >
                            Go to project settings
                        </LemonButton>
                    )}
                    {canGoBack && (
                        <LemonButton
                            fullWidth
                            type="secondary"
                            center
                            size="large"
                            onClick={() => window.history.back()}
                            data-attr="toolbar-oauth-error-go-back"
                        >
                            Go back
                        </LemonButton>
                    )}
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}

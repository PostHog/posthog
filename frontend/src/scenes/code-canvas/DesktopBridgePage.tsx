import { IconLaptop } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'

import { desktopBridgeDescription, openInDesktop } from './desktopBridge'

export interface DesktopBridgePageProps {
    /** What the interstitial is opening, e.g. "This canvas", "This task". Starts the explanatory sentence. */
    subject: string
    /** The `posthog-code(-dev)://…` URL to open, or null while its id isn't resolved yet. */
    deepLink: string | null
    /** The same item in the web app, for visitors who would rather not use the desktop app. Null when it has no web view. */
    webUrl?: string | null
}

/**
 * Shared page for the desktop-app bridge scenes (channel/task/loop links): an explanation, a manual
 * "open" button (in case the browser blocks the auto-redirect the scene fires on mount), an "open in
 * browser" button when the item also has a web view, and a download link for visitors without the app.
 */
export function DesktopBridgePage({ subject, deepLink, webUrl }: DesktopBridgePageProps): JSX.Element {
    return (
        <AuthScene notes={AUTH_NOTES.desktopBridge.default}>
            <AuthSceneCard>
                <div className="flex justify-center mb-3">
                    <IconLaptop className="text-5xl" />
                </div>
                <AuthCardTitle title="Opening in PostHog Desktop…" sub={desktopBridgeDescription(subject, !!webUrl)} />
                <div className="flex flex-col gap-2">
                    {deepLink && (
                        <LemonButton
                            type="primary"
                            size="large"
                            fullWidth
                            center
                            onClick={() => openInDesktop(deepLink)}
                        >
                            Open in desktop app
                        </LemonButton>
                    )}
                    {webUrl && (
                        <LemonButton
                            type="secondary"
                            size="large"
                            fullWidth
                            center
                            to={webUrl}
                            data-attr="desktop-bridge-open-in-browser"
                        >
                            Open in browser
                        </LemonButton>
                    )}
                </div>
                <p className="mt-4 mb-0 text-sm text-center">
                    <Link
                        to="https://posthog.com/desktop"
                        target="_blank"
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                    >
                        Download PostHog Desktop
                    </Link>
                </p>
            </AuthSceneCard>
        </AuthScene>
    )
}

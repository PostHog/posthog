import { IconLaptop } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'

import { desktopBridgeDescription, openInDesktop } from './desktopBridge'
import { QuillDesktopBridgeBody } from './QuillDesktopBridgeBody'

export interface DesktopBridgeBodyProps {
    /** What the interstitial is opening, e.g. "This canvas", "This task". Starts the explanatory sentence. */
    subject: string
    /** The `posthog-code(-dev)://…` URL to open, or null while its id isn't resolved yet. */
    deepLink: string | null
    /** The same item in the web app, for visitors who would rather not use the desktop app. Null when it has no web view. */
    webUrl?: string | null
}

/**
 * Shared body for the desktop-app bridge scenes (canvas/channel/task/loop links): an explanation,
 * a manual "open" button (in case the browser blocks the auto-redirect the scene fires on mount),
 * an "open in browser" button when the item also has a web view, and a download link for visitors without the app.
 */
export function DesktopBridgeBody({ subject, deepLink, webUrl }: DesktopBridgeBodyProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return <QuillDesktopBridgeBody subject={subject} deepLink={deepLink} webUrl={webUrl} />
    }
    return (
        <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
            <IconLaptop className="text-5xl shrink-0" />
            <h2 className="text-xl font-semibold m-0">Opening in PostHog Desktop…</h2>
            <p className="text-muted mb-0">{desktopBridgeDescription(subject, !!webUrl)}</p>
            <div className="flex flex-wrap justify-center gap-2">
                {deepLink && (
                    <LemonButton type="primary" onClick={() => openInDesktop(deepLink)}>
                        Open in desktop app
                    </LemonButton>
                )}
                {webUrl && (
                    <LemonButton type="secondary" to={webUrl} data-attr="desktop-bridge-open-in-browser">
                        Open in browser
                    </LemonButton>
                )}
            </div>
            <Link to="https://posthog.com/desktop" target="_blank">
                Download PostHog Desktop
            </Link>
        </div>
    )
}

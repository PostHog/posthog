import { IconLaptop } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface DesktopBridgeBodyProps {
    /** What the interstitial is opening, e.g. "This canvas", "This task". Starts the explanatory sentence. */
    subject: string
    /** The `posthog-code(-dev)://…` URL to open, or null while its id isn't resolved yet. */
    deepLink: string | null
}

/**
 * Shared body for the desktop-app bridge scenes (canvas/channel/task/loop links): an explanation,
 * a manual "open" button (in case the browser blocks the auto-redirect the scene fires on mount),
 * and a download link for visitors without the app installed.
 */
export function DesktopBridgeBody({ subject, deepLink }: DesktopBridgeBodyProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
            <IconLaptop className="text-5xl shrink-0" />
            <h2 className="text-xl font-semibold m-0">Opening in PostHog Desktop…</h2>
            <p className="text-muted mb-0">
                {subject} lives in the PostHog Desktop app. If it's installed, it should open automatically. If it
                didn't, use the button below, or download the app.
            </p>
            <div className="flex flex-col items-center gap-2">
                {deepLink && (
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            window.location.href = deepLink
                        }}
                    >
                        Open in PostHog Desktop
                    </LemonButton>
                )}
                <LemonButton type="secondary" to="https://posthog.com/desktop" targetBlank>
                    Download PostHog Desktop
                </LemonButton>
            </div>
        </div>
    )
}

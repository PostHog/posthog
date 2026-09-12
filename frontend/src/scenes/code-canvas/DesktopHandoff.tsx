import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DesktopHandoffStatus } from './useDesktopHandoff'

const DOWNLOAD_URL = 'https://posthog.com/desktop'

export interface DesktopHandoffProps {
    status: DesktopHandoffStatus
    /** Fires the deep link again. Absent when there is no link to fire. */
    onRetry?: () => void
    /** What the visitor came for, as a sentence: "This task lives in the PostHog Desktop app." */
    description: string
    view: string
}

/** Interstitial for the `/code/…` share links, which only resolve inside the desktop app. */
export function DesktopHandoff({ status, onRetry, description, view }: DesktopHandoffProps): JSX.Element {
    useEffect(() => {
        if (status === 'stalled') {
            // pinned: analytics event name — renaming breaks dashboards
            posthog.capture('desktop_handoff_stalled', { view })
        }
    }, [status, view])

    return (
        <BridgePage view={view}>
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                {status === 'stalled' ? (
                    <>
                        <h2 className="text-xl font-semibold m-0">PostHog Desktop didn't open</h2>
                        <p className="text-muted mb-0">
                            {`${description} Nothing on this computer answered the link, so the app may not be installed yet.`}
                        </p>
                        {onRetry && (
                            <LemonButton type="primary" data-attr="desktop-handoff-retry" onClick={onRetry}>
                                Try again
                            </LemonButton>
                        )}
                    </>
                ) : (
                    <>
                        <h2 className="text-xl font-semibold m-0">Opening in PostHog Desktop…</h2>
                        <p className="text-muted mb-0">{description}</p>
                        <Spinner className="text-2xl" />
                    </>
                )}
                <LemonButton type="secondary" data-attr="desktop-handoff-download" to={DOWNLOAD_URL} targetBlank>
                    Download PostHog Desktop
                </LemonButton>
            </div>
        </BridgePage>
    )
}

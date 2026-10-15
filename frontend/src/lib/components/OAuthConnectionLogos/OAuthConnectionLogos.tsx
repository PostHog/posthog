import { useState } from 'react'

import { IconPlug } from '@posthog/icons'

import { Logomark } from 'lib/brand'

export function OAuthConnectionLogos({ appName, logoUri }: { appName: string; logoUri: string | null }): JSX.Element {
    const [logoFailed, setLogoFailed] = useState(false)
    const resolvedLogoUri = logoFailed ? null : logoUri

    return (
        // pinned: `data-attr` value read by autocapture dashboards, so it keeps the name it was
        // first shipped under on the login page.
        <div className="flex items-center justify-center gap-3 mb-4" data-attr="pending-oauth-connection-logos">
            <span className="flex items-center justify-center w-12 h-12 p-2.5 rounded-full border border-border bg-bg-light">
                <Logomark size="sm" />
            </span>
            <IconPlug className="text-secondary text-lg shrink-0" aria-hidden />
            <span className="flex items-center justify-center w-12 h-12 rounded-full border border-border bg-bg-light overflow-hidden">
                {resolvedLogoUri ? (
                    <img
                        src={resolvedLogoUri}
                        alt={`${appName} logo`}
                        className="w-8 h-8 object-contain"
                        referrerPolicy="no-referrer"
                        onError={() => setLogoFailed(true)}
                    />
                ) : (
                    <span className="text-lg font-semibold text-primary" aria-hidden>
                        {appName.charAt(0).toUpperCase()}
                    </span>
                )}
            </span>
        </div>
    )
}

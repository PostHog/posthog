import { useState } from 'react'

import { IconPlug } from '@posthog/icons'

import { Logomark } from 'lib/brand'

import type { PendingOAuthConnection } from '../pendingOAuthConnectionLogic'

export function PendingOAuthConnectionLogos({ connection }: { connection: PendingOAuthConnection }): JSX.Element {
    const [logoFailed, setLogoFailed] = useState(false)
    const logoUri = logoFailed ? null : connection.logoUri

    return (
        <div className="flex items-center justify-center gap-3 mb-4" data-attr="pending-oauth-connection-logos">
            <span className="flex items-center justify-center w-12 h-12 p-2.5 rounded-full border border-border bg-bg-light">
                <Logomark variant="gradient" size="sm" />
            </span>
            <IconPlug className="text-secondary text-lg shrink-0" aria-hidden />
            <span className="flex items-center justify-center w-12 h-12 rounded-full border border-border bg-bg-light overflow-hidden">
                {logoUri ? (
                    <img
                        src={logoUri}
                        alt={`${connection.clientName} logo`}
                        className="w-8 h-8 object-contain"
                        referrerPolicy="no-referrer"
                        onError={() => setLogoFailed(true)}
                    />
                ) : (
                    <span className="text-lg font-semibold text-primary" aria-hidden>
                        {connection.clientName.charAt(0).toUpperCase()}
                    </span>
                )}
            </span>
        </div>
    )
}

import { useValues } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

// pinned: the analytics event name and data-attr values in this file feed dashboards, so renaming them breaks them.

interface NoticeLink {
    target: string
    label: string
    to: () => string
}

const NOTICES: Record<'queries' | 'access', { text: string; links: NoticeLink[] }> = {
    queries: {
        text: 'Monitoring and history moved to Queries.',
        links: [{ target: 'queries', label: 'Open Queries', to: urls.warehouseQueries }],
    },
    access: {
        text: 'Connection details and logins moved.',
        links: [
            { target: 'connect', label: 'Open Connect', to: urls.warehouseConnect },
            { target: 'access', label: 'Open Access', to: urls.warehouseAccess },
        ],
    },
}

/** Points to the Warehouse console page that replaces part of this Data ops tab. Hidden without the console flag. */
export function WarehouseConsoleMovedNotice({ target }: { target: keyof typeof NOTICES }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]) {
        return null
    }
    const { text, links } = NOTICES[target]
    return (
        <LemonBanner type="info" className="mt-4">
            {text}{' '}
            {links.map((link, index) => (
                <span key={link.target}>
                    {index > 0 && ' · '}
                    <Link
                        to={link.to()}
                        onClick={() =>
                            posthog.capture('warehouse console moved notice clicked', { target: link.target })
                        }
                        data-attr={`data-ops-moved-notice-${link.target}`}
                    >
                        {link.label}
                    </Link>
                </span>
            ))}
        </LemonBanner>
    )
}

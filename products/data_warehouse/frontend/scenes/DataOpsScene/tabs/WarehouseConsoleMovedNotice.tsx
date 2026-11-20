import { useValues } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

// pinned: the analytics event name in this file feeds dashboards, so renaming it breaks them.

const TARGETS = {
    queries: { text: 'Monitoring and history moved to Queries.', to: urls.warehouseQueries, label: 'Open Queries' },
    access: { text: 'Logins are also managed in Access.', to: urls.warehouseAccess, label: 'Open Access' },
} as const

/** Points to the Warehouse console page that replaces part of this Data ops tab. Hidden without the console flag. */
export function WarehouseConsoleMovedNotice({ target }: { target: keyof typeof TARGETS }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]) {
        return null
    }
    const { text, to, label } = TARGETS[target]
    return (
        <LemonBanner type="info" className="mt-4">
            {text}{' '}
            <Link
                to={to()}
                onClick={() => posthog.capture('warehouse console moved notice clicked', { target })}
                data-attr={`data-ops-moved-notice-${target}`}
            >
                {label}
            </Link>
        </LemonBanner>
    )
}

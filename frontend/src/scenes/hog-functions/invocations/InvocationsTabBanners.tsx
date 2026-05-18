import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

/**
 * Shown at the top of legacy debugging tabs (Logs, Testing, the workflow
 * "Invocations" logs view) while the new Invocations tab is in preview. Gated
 * on the same flag the new tab is — so legacy users without the flag never see
 * any of this, and preview users get a one-line nudge that the tab is moving.
 *
 * Dismissable via `dismissKey` so the banner only nags once per browser.
 */
export function InvocationsLegacyTabBanner({
    legacyTab,
}: {
    legacyTab: 'Logs' | 'Testing' | 'Invocations (legacy)'
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.HOG_INVOCATION_RESULTS_RUNS_TAB]) {
        return null
    }
    return (
        <LemonBanner
            type="info"
            dismissKey={`invocations-legacy-${legacyTab.toLowerCase().replace(/\s+/g, '-')}-banner`}
            className="mb-2"
        >
            The new <strong>Invocations</strong> tab is rolling out and will replace this {legacyTab} view once it's
            generally available. Try it from the tab bar above.
        </LemonBanner>
    )
}

/**
 * Banner shown at the top of the new Invocations tab itself. Parent gates the
 * tab on the flag already so we don't re-check here — if you're reading this
 * banner, the flag is on for you.
 */
export function InvocationsBetaBanner(): JSX.Element {
    return (
        <LemonBanner type="info" dismissKey="invocations-beta-banner" className="mb-2">
            <div className="deprecated-space-y-1">
                <div>
                    <strong>Invocations</strong> is in beta and will replace the Logs and Testing tabs once it's GA.
                </div>
                <ul className="ml-4 list-disc text-sm">
                    <li>One row per invocation with the full lifecycle (queued → running → succeeded / failed)</li>
                    <li>Filters on status, error kind, retries, and free-text by event / distinct / person ID</li>
                    <li>Single-row replay + bulk "Re-run…" by window + filter</li>
                    <li>Auto-refresh while anything is in flight</li>
                    <li>Re-run jobs appear in the list themselves so you can debug them the same way</li>
                </ul>
                <div className="text-muted-alt text-xs">Found something missing or broken? Let the CDP team know.</div>
            </div>
        </LemonBanner>
    )
}

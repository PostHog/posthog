import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
            type="warning"
            dismissKey={`invocations-legacy-${legacyTab.toLowerCase().replace(/\s+/g, '-')}-banner`}
            className="mb-2"
        >
            This {legacyTab} view will be replaced by the new <strong>Invocations</strong> tab soon.
        </LemonBanner>
    )
}

export function InvocationsBetaBanner(): JSX.Element {
    return (
        <LemonBanner type="warning" dismissKey="invocations-beta-banner" className="mb-2">
            Invocations is in beta — it will replace the Logs and Testing tabs.
        </LemonBanner>
    )
}

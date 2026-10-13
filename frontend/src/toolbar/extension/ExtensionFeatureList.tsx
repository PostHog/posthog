import { useActions, useValues } from 'kea'

import { IconBolt, IconCursorClick, IconExternal, IconFlask, IconPieChart, IconToggle } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { ToolbarFeatureGateStatus, toolbarFeatureGateStatus } from '~/toolbar/toolbarEntitlementsLogic'
import { useToolbarFeatureFlag } from '~/toolbar/toolbarPosthogJS'

import { EXTENSION_FEATURE_ENTRY_POINTS, ExtensionFeatureEntryPoint, ExtensionFeatureKey } from './extensionFeatures'
import { extensionPopupLogic } from './extensionPopupLogic'

const FEATURE_ICONS: Record<ExtensionFeatureKey, JSX.Element> = {
    heatmaps: <IconCursorClick />,
    actions: <IconBolt />,
    'feature-flags': <IconToggle />,
    'web-vitals': <IconPieChart />,
    experiments: <IconFlask />,
}

export const GATE_DISABLED_REASONS: Record<ToolbarFeatureGateStatus, string | null> = {
    available: null,
    checking: 'Checking plan access…',
    unknown: "Couldn't check plan access. Open the popup again to retry.",
    locked: 'Needs a pay-as-you-go subscription',
}

function ExtensionFeatureButton({ entryPoint }: { entryPoint: ExtensionFeatureEntryPoint }): JSX.Element {
    const { entitlements } = useValues(extensionPopupLogic)
    const { openFeature } = useActions(extensionPopupLogic)
    // Hooks run unconditionally, so features without a gate read the flag and ignore it.
    const rolloutEnabled = useToolbarFeatureFlag(entryPoint.gate?.rolloutFlag ?? FEATURE_FLAGS.TOOLBAR_PAID_HEATMAPS)
    const gateStatus = entryPoint.gate
        ? toolbarFeatureGateStatus(entryPoint.gate.feature, rolloutEnabled, entitlements, false)
        : 'available'

    return (
        <LemonButton
            fullWidth
            icon={FEATURE_ICONS[entryPoint.key]}
            sideIcon={<IconExternal />}
            disabledReason={GATE_DISABLED_REASONS[gateStatus]}
            tooltip={`${entryPoint.description}. Opens in PostHog.`}
            onClick={() => openFeature(entryPoint.key, entryPoint.path)}
            data-attr={`toolbar-extension-feature-${entryPoint.key}`}
        >
            {entryPoint.label}
        </LemonButton>
    )
}

export function ExtensionFeatureList({ origin }: { origin: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="text-secondary text-xs">Toolbar tools for {new URL(origin).host}</div>
            {EXTENSION_FEATURE_ENTRY_POINTS.map((entryPoint) => (
                <ExtensionFeatureButton key={entryPoint.key} entryPoint={entryPoint} />
            ))}
        </div>
    )
}

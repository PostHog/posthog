import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { ToolbarFeatureGateStatus, toolbarFeatureGateStatus } from '~/toolbar/shared/toolbarEntitlementsLogic'
import { useToolbarFeatureFlag } from '~/toolbar/shared/toolbarPosthogJS'

import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import type { PageToolDefinition } from './extensionPageTools'

const GATE_DISABLED_REASONS: Record<ToolbarFeatureGateStatus, string | null> = {
    available: null,
    checking: 'Checking plan access…',
    unknown: "Couldn't check plan access. Close and open the panel to try again.",
    locked: 'Needs a pay-as-you-go subscription',
}

/** Applies the floating toolbar's plan gate to the panel's tools. */
export function usePageToolDisabledReason(): (tool: PageToolDefinition) => string | null {
    const { entitlements } = useValues(extensionPanelLogic)
    const rolloutEnabled = useToolbarFeatureFlag(FEATURE_FLAGS.TOOLBAR_PAID_HEATMAPS)
    return (tool) =>
        tool.gate
            ? GATE_DISABLED_REASONS[toolbarFeatureGateStatus(tool.gate, rolloutEnabled, entitlements, false)]
            : null
}

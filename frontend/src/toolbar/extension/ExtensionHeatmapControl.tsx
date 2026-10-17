import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { toolbarFeatureGateStatus } from '~/toolbar/toolbarEntitlementsLogic'
import { useToolbarFeatureFlag } from '~/toolbar/toolbarPosthogJS'
import { AvailableFeature } from '~/types'

import { GATE_DISABLED_REASONS } from './ExtensionFeatureList'
import { extensionPageToolsLogic } from './extensionPageToolsLogic'
import { extensionPopupLogic } from './extensionPopupLogic'

export function ExtensionHeatmapControl(): JSX.Element {
    const { entitlements } = useValues(extensionPopupLogic)
    const { contentStatus, contentStatusLoading, heatmapError } = useValues(extensionPageToolsLogic)
    const { showHeatmap, hideHeatmap } = useActions(extensionPageToolsLogic)
    const rolloutEnabled = useToolbarFeatureFlag(FEATURE_FLAGS.TOOLBAR_PAID_HEATMAPS)
    const gateStatus = toolbarFeatureGateStatus(AvailableFeature.TOOLBAR_HEATMAPS, rolloutEnabled, entitlements, false)
    const shown = contentStatus.heatmapElementCount !== null

    return (
        <div className="flex flex-col gap-1">
            <LemonSwitch
                fullWidth
                bordered
                label="Show heatmap on this page"
                checked={shown}
                loading={contentStatusLoading}
                disabledReason={GATE_DISABLED_REASONS[gateStatus]}
                onChange={(checked) => (checked ? showHeatmap() : hideHeatmap())}
                data-attr="toolbar-extension-heatmap-toggle"
            />
            {shown && (
                <div className="text-secondary text-xs">
                    {contentStatus.heatmapElementCount === 0
                        ? 'No clicked elements found on this page in the last 7 days.'
                        : `${contentStatus.heatmapElementCount} clicked elements in the last 7 days.`}
                </div>
            )}
            {heatmapError && <div className="text-danger text-xs">Couldn't load heatmap data. Try again.</div>}
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'

import type { ComparisonMode } from 'lib/components/VisualImageDiffViewer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { FlagComparisonDiff } from '~/toolbar/shared/flags/FlagComparisonDiff'

import { extensionFlagsLogic } from '../../logics/panel/extensionFlagsLogic'

export function ExtensionFlagComparison(): JSX.Element | null {
    const { flagComparison, beforeCapture, afterCapture, onCaptures } = useValues(extensionFlagsLogic)
    const { closeComparison, setAfterValue } = useActions(extensionFlagsLogic)
    // Side by side gives each image half of a narrow panel, so the panel opens on the split view.
    const [mode, setMode] = useState<ComparisonMode>('split')

    if (!flagComparison || !beforeCapture || !afterCapture) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1">
                <LemonButton
                    size="small"
                    icon={<IconArrowLeft />}
                    tooltip="Back to the flags"
                    onClick={closeComparison}
                    data-attr="toolbar-extension-flag-comparison-back"
                />
                <span className="flex-1 truncate font-semibold" translate="no">
                    {flagComparison.flagKey}
                </span>
            </div>
            <span className="text-xs text-secondary">
                {`Before shows the page with the flag off. After shows it with ${
                    onCaptures.length > 1 ? `the ${afterCapture.label} variant` : 'the flag on'
                }.`}
            </span>
            <FlagComparisonDiff
                before={beforeCapture}
                after={afterCapture}
                onCaptures={onCaptures}
                identical={flagComparison.identical}
                onAfterValueChange={setAfterValue}
                mode={mode}
                onModeChange={setMode}
            />
        </div>
    )
}

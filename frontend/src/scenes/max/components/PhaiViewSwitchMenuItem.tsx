import { useActions, useValues } from 'kea'

import { IconRevert, IconSparkles } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import type { PhaiViewMode } from '~/layout/ai/aiPanelIds'

import { maxGlobalLogic } from '../maxGlobalLogic'

export function PhaiViewSwitchMenuItem({ onChange }: { onChange?: (mode: PhaiViewMode) => void }): JSX.Element | null {
    const { isPhaiSandboxFlagOn, effectivePhaiView } = useValues(maxGlobalLogic)
    const { setPhaiViewMode } = useActions(maxGlobalLogic)

    if (!isPhaiSandboxFlagOn) {
        return null
    }
    const mode: PhaiViewMode = effectivePhaiView === 'new' ? 'legacy' : 'new'
    return (
        <DropdownMenuItem
            onClick={() => {
                setPhaiViewMode(mode)
                onChange?.(mode)
            }}
            data-attr={`phai-switch-to-${mode}`}
        >
            {mode === 'legacy' ? <IconRevert /> : <IconSparkles />}
            {mode === 'legacy' ? 'Switch to legacy view' : 'Switch to new view'}
        </DropdownMenuItem>
    )
}

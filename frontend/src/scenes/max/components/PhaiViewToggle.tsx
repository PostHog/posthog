import { useActions, useValues } from 'kea'

import { IconRevert, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { PhaiViewMode, maxGlobalLogic } from '../maxGlobalLogic'

/**
 * Switches the Max scene between the new posthog_ai/frontend surface and the legacy Max chat. Only
 * rendered for users on the sandbox flag; the new surface is their default (see `effectivePhaiView`).
 *
 * `lemon` matches the small secondary buttons in the main `/ai` header; `primitive` matches the
 * icon-only chrome around "Open as main focus" in the side-panel header.
 */
export function PhaiViewToggle({
    variant = 'lemon',
    onChange,
}: {
    variant?: 'lemon' | 'primitive'
    /** Runs after the saved view changes, for a host that has to follow the switch (e.g. leave a pinned chat). */
    onChange?: (mode: PhaiViewMode) => void
}): JSX.Element | null {
    const { isPhaiSandboxFlagOn, effectivePhaiView } = useValues(maxGlobalLogic)
    const { setPhaiViewMode } = useActions(maxGlobalLogic)

    if (!isPhaiSandboxFlagOn) {
        return null
    }

    const switchingToLegacy = effectivePhaiView === 'new'
    const tooltip = switchingToLegacy ? 'Switch to legacy PostHog AI' : 'Switch to new PostHog AI'
    const Icon = switchingToLegacy ? IconRevert : IconSparkles
    const onClick = (): void => {
        const mode: PhaiViewMode = switchingToLegacy ? 'legacy' : 'new'
        setPhaiViewMode(mode)
        onChange?.(mode)
    }

    if (variant === 'primitive') {
        return (
            <ButtonPrimitive iconOnly onClick={onClick} tooltip={tooltip} tooltipPlacement="bottom-end">
                <Icon className="text-tertiary size-3 group-hover:text-primary z-10" />
            </ButtonPrimitive>
        )
    }

    return (
        <LemonButton size="small" type="secondary" sideIcon={<Icon />} onClick={onClick} tooltip={tooltip}>
            {switchingToLegacy ? 'Legacy view' : 'New view'}
        </LemonButton>
    )
}

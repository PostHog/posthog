import { IconSearch } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

interface NavSearchButtonProps {
    isLayoutNavCollapsed: boolean
    toggleCommand: () => void
}

export function NavSearchButton({ isLayoutNavCollapsed, toggleCommand }: NavSearchButtonProps): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly
            data-attr="nav-search"
            tooltip={
                <div className="flex items-center gap-2">
                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                </div>
            }
            tooltipPlacement={isLayoutNavCollapsed ? 'right' : undefined}
            onClick={() => {
                posthog.capture('nav search clicked')
                toggleCommand()
            }}
        >
            <IconSearch className="size-4 shrink-0 text-secondary" />
        </ButtonPrimitive>
    )
}

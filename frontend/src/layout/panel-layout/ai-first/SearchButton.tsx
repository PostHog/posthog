import { IconSearch } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

interface SearchButtonProps {
    isLayoutNavCollapsed: boolean
    toggleCommand: () => void
}

export function SearchButton({ isLayoutNavCollapsed, toggleCommand }: SearchButtonProps): JSX.Element {
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
            <IconSearch className="size-4 text-secondary" />
        </ButtonPrimitive>
    )
}

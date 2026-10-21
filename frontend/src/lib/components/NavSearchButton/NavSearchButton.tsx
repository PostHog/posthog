import { IconSearch } from '@posthog/icons'

import { CommandOpenSource } from 'lib/components/Command/commandLogic'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export function NavSearchButton({
    toggleCommand,
    showShortcut = false,
}: {
    toggleCommand: (source: CommandOpenSource) => void
    showShortcut?: boolean
}): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly={!showShortcut}
            className={showShortcut ? 'shrink-0 px-1' : undefined}
            aria-label="Search"
            data-attr={showShortcut ? 'nav-search-bar' : 'nav-search'}
            tooltip={
                <div className="flex items-center gap-2">
                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                </div>
            }
            tooltipPlacement="right"
            onClick={() => {
                posthog.capture('nav search clicked')
                toggleCommand(showShortcut ? 'nav-search-bar' : 'nav-search-button')
            }}
        >
            <IconSearch className="size-4 shrink-0 text-secondary" />
            {showShortcut && <RenderKeybind keybind={[keyBinds.search]} />}
        </ButtonPrimitive>
    )
}

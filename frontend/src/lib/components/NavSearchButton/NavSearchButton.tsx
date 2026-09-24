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
            className={showShortcut ? 'shrink-0' : undefined}
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

/** Input-styled full-width search trigger shown below the nav header when the nav is expanded. */
export function NavSearchBar({ toggleCommand }: { toggleCommand: (source: CommandOpenSource) => void }): JSX.Element {
    return (
        <ButtonPrimitive
            fullWidth
            data-attr="nav-search-bar"
            className="justify-between border border-primary bg-surface-primary rounded-md px-2"
            onClick={() => {
                posthog.capture('nav search clicked')
                toggleCommand('nav-search-bar')
            }}
        >
            <span className="flex items-center gap-1.5 text-secondary">
                <IconSearch className="size-4 shrink-0" />
                <span className="text-xs">Search</span>
            </span>
            <RenderKeybind keybind={[keyBinds.search]} />
        </ButtonPrimitive>
    )
}

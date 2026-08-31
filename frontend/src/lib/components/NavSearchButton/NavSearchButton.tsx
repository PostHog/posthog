import { IconSearch } from '@posthog/icons'

import { CommandOpenSource } from 'lib/components/Command/commandLogic'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

/** Icon-only search trigger, used in the collapsed nav where there is no room for the search bar. */
export function NavSearchButton({
    openCommand,
    isCommandOpen,
}: {
    openCommand: (source: CommandOpenSource) => void
    isCommandOpen: boolean
}): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly
            data-attr="nav-search"
            active={isCommandOpen}
            aria-pressed={isCommandOpen}
            tooltip={
                <div className="flex items-center gap-2">
                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                </div>
            }
            tooltipPlacement="right"
            onClick={() => {
                posthog.capture('nav search clicked')
                openCommand('nav-search-button')
            }}
        >
            <IconSearch className="size-4 shrink-0 text-secondary" />
        </ButtonPrimitive>
    )
}

/** Input-styled full-width search trigger shown below the nav header when the nav is expanded. */
export function NavSearchBar({
    openCommand,
    isCommandOpen,
}: {
    openCommand: (source: CommandOpenSource) => void
    isCommandOpen: boolean
}): JSX.Element {
    return (
        <ButtonPrimitive
            fullWidth
            data-attr="nav-search-bar"
            active={isCommandOpen}
            aria-pressed={isCommandOpen}
            className="justify-between border border-primary bg-surface-primary rounded-md px-2"
            onClick={() => {
                posthog.capture('nav search clicked')
                openCommand('nav-search-bar')
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

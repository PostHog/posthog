import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

interface NavSearchButtonProps {
    isLayoutNavCollapsed: boolean
}

export function NavSearchButton({ isLayoutNavCollapsed }: NavSearchButtonProps): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { openCommand } = useActions(commandLogic)

    return (
        <ButtonPrimitive
            iconOnly
            active={isCommandOpen}
            aria-pressed={isCommandOpen}
            data-attr="nav-search"
            tooltip={
                <div className="flex items-center gap-2">
                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                </div>
            }
            tooltipPlacement={isLayoutNavCollapsed ? 'right' : undefined}
            onClick={() => {
                posthog.capture('nav search clicked')
                openCommand('nav-search-button')
            }}
        >
            <IconSearch className="size-4 shrink-0 text-secondary" />
        </ButtonPrimitive>
    )
}

/** Input-styled full-width search trigger shown below the nav header in the `search-bar` variant of the Cmd+K nav experiment. */
export function NavSearchBar(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { openCommand } = useActions(commandLogic)

    return (
        <ButtonPrimitive
            fullWidth
            active={isCommandOpen}
            aria-pressed={isCommandOpen}
            data-attr="nav-search-bar"
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

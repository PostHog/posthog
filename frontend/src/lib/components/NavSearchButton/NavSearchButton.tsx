import { useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { searchButtonLogic } from './searchButtonLogic'

interface NavSearchButtonProps {
    isLayoutNavCollapsed: boolean
    toggleCommand: () => void
}

export function NavSearchButton({ isLayoutNavCollapsed, toggleCommand }: NavSearchButtonProps): JSX.Element {
    const { showHint } = useValues(searchButtonLogic)

    return (
        <ButtonPrimitive
            iconOnly={!showHint}
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
            className="gap-0"
        >
            <IconSearch className="size-4 shrink-0 text-secondary" />
            <div
                className={`overflow-hidden whitespace-nowrap transition-[max-width,opacity] duration-300 ease-in-out ${
                    showHint ? 'max-w-xs opacity-100' : 'max-w-0 opacity-0'
                }`}
            >
                <span className="flex items-center gap-1 pl-1 text-xs text-secondary">
                    <RenderKeybind keybind={[keyBinds.search]} minimal />
                </span>
            </div>
        </ButtonPrimitive>
    )
}
